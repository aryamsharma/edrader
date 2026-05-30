#!/usr/bin/env python3
"""
Loadtest: measure EventBus dispatch latency for N events.

Each step adds a subscriber.
"""

import asyncio
import sys
import time
from collections import defaultdict
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


async def main() -> None:
    csv = sys.argv[1]
    feed = HistoricalFeed()
    feed.load_csv(csv, symbol="TEST")
    events = feed.events
    n = len(events)
    print(f"Events: {n}")

    bus = EventBus(max_queue_size=1_000_000)

    # Subscriber 1: example strategy (emits SignalGeneratedEvent)
    sma = SmaCrossoverStrategy("sma", bus, fast_window=5, slow_window=15)
    await sma.start()
    print(f"Subscribers: {bus.subscriber_count}")

    # Subscriber 2: risk engine (validates signals -> approved/rejected)
    risk = RiskEngine(
        bus, max_position_size=500, max_daily_loss=50_000.0, max_concurrent_positions=50
    )
    await risk.start()
    print(f"Subscribers: {bus.subscriber_count}")

    # Subscriber 3: execution engine (sizing, throttling, order submission)
    exec_engine = ExecutionEngine(bus, default_order_type="MKT", throttle_delay=0.0, max_retries=0)
    await exec_engine.start()
    print(f"Subscribers: {bus.subscriber_count}")

    # Subscriber 4: simulated broker (fills orders, publishes fill events)
    broker = SimulatedBroker(bus, slippage_bps=5.0, commission_per_trade=1.50)
    await broker.start()
    print(f"Subscribers: {bus.subscriber_count}")

    # Subscriber 6: position manager (PnL + exposure tracking)
    pm = PositionManager(bus)
    await pm.start()
    print(f"Subscribers: {bus.subscriber_count}")

    # Subscriber 7: metrics engine (performance metrics)
    metrics = MetricsEngine(bus, initial_capital=100_000.0)
    await metrics.start()
    print(f"Subscribers: {bus.subscriber_count}")

    # Subscriber 8: in-memory journal (just counts events by type)
    counts: defaultdict[str, int] = defaultdict(int)

    async def mem_journal(event: BaseEvent) -> None:
        counts[type(event).__name__] += 1

    bus.subscribe_all(mem_journal, name="mem_journal")
    print(f"Subscribers: {bus.subscriber_count}")

    await bus.start()

    t0 = time.monotonic()
    for ev in events:
        await bus.publish(ev)
    t1 = time.monotonic()
    pub = t1 - t0

    await bus.drain()
    t2 = time.monotonic()
    drn = t2 - t1

    snap = bus.metrics.snapshot()
    print(
        f"\nPublished {snap['total_published']}, "
        f"dispatched {snap['total_dispatched']}, errors {snap['total_errors']}"
    )
    print(f"Publish: {pub:.4f}s  ({n / pub:,.0f} ev/s)")
    print(f"Drain:   {drn:.4f}s  ({n / drn:,.0f} ev/s)")
    print(f"Total:   {pub + drn:.4f}s")

    print("\nEvents by type:")
    for t, c in sorted(counts.items()):
        print(f"  {t}: {c}")

    await sma.stop()
    await risk.stop()
    await exec_engine.stop()
    await broker.stop()
    await pm.stop()
    await metrics.stop()
    await bus.stop()


if __name__ == "__main__":
    asyncio.run(main())
