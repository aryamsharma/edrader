#!/usr/bin/env python3
"""
Compare async vs sync dispatch latency with 1000 bar events.
Runs the full pipeline (strategy → risk → exec → broker → pm → metrics) in each mode.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from edrader.events.bus import EventBus
from edrader.events.event_types import BaseEvent
from edrader.execution.engine import ExecutionEngine
from edrader.portfolio.position import PositionManager
from edrader.replay.historical_feed import HistoricalFeed
from edrader.replay.metrics import MetricsEngine
from edrader.replay.simulated_broker import SimulatedBroker
from edrader.risk.engine import RiskEngine
from edrader.strategies.examples.sma_crossover import SmaCrossoverStrategy


def _counter(counts: dict[str, int]):
    async def count(event: BaseEvent) -> None:
        counts[type(event).__name__] = counts.get(type(event).__name__, 0) + 1

    return count


def build_pipeline(bus: EventBus) -> list:
    pm = PositionManager(bus)
    risk = RiskEngine(
        bus,
        position_manager=pm,
        max_position_size=500,
        max_daily_loss=50_000.0,
        max_concurrent_positions=50,
    )
    exec_engine = ExecutionEngine(bus, default_order_type="MKT", throttle_delay=0.0, max_retries=0)
    broker = SimulatedBroker(bus, slippage_bps=5.0, commission_per_trade=1.50)
    sma = SmaCrossoverStrategy("sma", bus, fast_window=5, slow_window=15)
    metrics = MetricsEngine(bus, initial_capital=100_000.0)
    return [pm, risk, exec_engine, broker, sma, metrics]


async def start_all(components: list) -> None:
    for c in components:
        await c.start()


async def stop_all(components: list) -> None:
    for c in reversed(components):
        await c.stop()


async def run_async(events: list) -> dict:
    bus = EventBus(max_queue_size=1_000_000)
    counts: dict[str, int] = {}
    bus.subscribe_all(_counter(counts), name="counter")
    components = build_pipeline(bus)
    await start_all(components)
    await bus.start()
    await asyncio.sleep(0)

    t0 = time.monotonic()
    for ev in events:
        await bus.publish(ev)
    t1 = time.monotonic()

    await bus.drain()
    t2 = time.monotonic()

    snap = bus.metrics.snapshot()

    await bus.stop()
    await stop_all(components)

    return {
        "publish": t1 - t0,
        "drain": t2 - t1,
        "total": t2 - t0,
        "published": snap["total_published"],
        "dispatched": snap["total_dispatched"],
        "counts": dict(sorted(counts.items())),
    }


async def run_sync(events: list) -> dict:
    bus = EventBus(max_queue_size=1_000_000)
    counts: dict[str, int] = {}
    bus.subscribe_all(_counter(counts), name="counter")
    bus.sync_mode = True
    components = build_pipeline(bus)
    await start_all(components)

    t0 = time.monotonic()
    for ev in events:
        await bus.publish(ev)
    t1 = time.monotonic()

    snap = bus.metrics.snapshot()

    await stop_all(components)

    return {
        "publish": t1 - t0,
        "drain": 0.0,
        "total": t1 - t0,
        "published": snap["total_published"],
        "dispatched": snap["total_dispatched"],
        "counts": dict(sorted(counts.items())),
    }


async def main() -> None:
    csv = sys.argv[1]
    feed = HistoricalFeed()
    feed.load_csv(csv, symbol="TEST")
    events = feed.events
    n = len(events)
    print(f"Events: {n}\n")

    print("=== Async mode ===")
    result_async = await run_async(events)
    print(f"  Published {result_async['published']}, dispatched {result_async['dispatched']}")
    print(f"  Publish: {result_async['publish']:.6f}s  ({n / result_async['publish']:,.0f} ev/s)")
    print(
        f"  Drain:   {result_async['drain']:.6f}s  ({n / result_async['drain']:,.0f} ev/s)"
        if result_async["drain"] > 0
        else "  Drain:   N/A"
    )
    print(f"  Total:   {result_async['total']:.6f}s")

    print()
    print("=== Sync mode ===")
    result_sync = await run_sync(events)
    print(f"  Published {result_sync['published']}, dispatched {result_sync['dispatched']}")
    print(f"  Publish: {result_sync['publish']:.6f}s  ({n / result_sync['publish']:,.0f} ev/s)")
    print(f"  Total:   {result_sync['total']:.6f}s")

    print()
    print("--- Event Counts ---")
    all_types = sorted(set(result_async["counts"]) | set(result_sync["counts"]))
    print(f"  {'Event Type':<30} {'Async':>8} {'Sync':>8}")
    for t in all_types:
        a = result_async["counts"].get(t, 0)
        s = result_sync["counts"].get(t, 0)
        diff = s - a
        marker = " ***" if diff != 0 else ""
        print(f"  {t:<30} {a:>8} {s:>8}{marker}")

    print()
    ratio = (
        result_async["total"] / result_sync["total"] if result_sync["total"] > 0 else float("inf")
    )
    print("--- Comparison ---")
    at = result_async
    a_str = f"  Async total: {at['total']:.6f}s  ({at['published']} pub / {at['dispatched']} disp)"
    st = result_sync
    s_str = f"  Sync total:  {st['total']:.6f}s  ({st['published']} pub / {st['dispatched']} disp)"
    print(a_str)
    print(s_str)
    print(f"  Sync is {ratio:.2f}x {'faster' if ratio > 1 else 'slower'} than async")


if __name__ == "__main__":
    asyncio.run(main())
