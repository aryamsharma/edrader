import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from edrader.events.bus import EventBus
from edrader.events.event_types import BaseEvent
from edrader.events.journal import EventJournal
from edrader.execution.engine import ExecutionEngine
from edrader.monitoring.logging import setup_logging
from edrader.portfolio.position import PositionManager
from edrader.replay import (
    HistoricalFeed,
    MetricsEngine,
    ReplayClock,
    ReplayEngine,
    SimulatedBroker,
)
from edrader.risk.engine import RiskEngine
from edrader.strategies.base import StrategyLoader
from edrader.strategies.examples.mean_reversion import MeanReversionStrategy
from edrader.strategies.examples.sma_crossover import SmaCrossoverStrategy
from edrader.strategies.examples.vwap_reversion import VwapReversionStrategy


async def run_backtest(
    csv_path: str,
    symbol: str,
    speed: float,
    max_bars: int | None = None,
    use_journal: bool = False,
    verbose: bool = False,
    tick_mode: bool = False,
) -> None:
    setup_logging("DEBUG" if verbose else "WARNING")
    bus = EventBus(max_queue_size=100_000)
    await bus.start()

    journal = None
    if use_journal:
        import tempfile

        journal_db = tempfile.mktemp(suffix=".db")
        journal = EventJournal(
            database_url=f"sqlite:///{journal_db}",
            batch_size=0,
            fast_mode=True,
        )

        async def journal_handler(event: BaseEvent) -> None:
            await journal.append(event)

        bus.subscribe_all(journal_handler, name="journal")

    if tick_mode:
        vwap = VwapReversionStrategy(
            "vwap_reversion", bus, window=500, entry_pct=0.005, exit_pct=0.001
        )
        strategies = [vwap]
    else:
        sma = SmaCrossoverStrategy("sma_crossover", bus, fast_window=10, slow_window=30)
        mr = MeanReversionStrategy("mean_reversion", bus, window=20, entry_z=2.0, exit_z=0.5)
        strategies = [sma, mr]

    loader = StrategyLoader()
    for strat in strategies:
        loader.register(strat.strategy_id, type(strat))

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
    metrics = MetricsEngine(bus, initial_capital=100_000.0)

    for component in [risk, exec_engine, broker, pm, metrics]:
        await component.start()

    for strat in strategies:
        await strat.start()

    feed = HistoricalFeed()
    clock = ReplayClock()
    clock.speed = speed
    engine = ReplayEngine(bus, clock=clock)

    if tick_mode:
        feed.load_tick_csv(csv_path, symbol=symbol)
        event_label = "ticks"
    else:
        feed.load_csv(csv_path, symbol=symbol)
        event_label = "bars"
    events = feed.events
    if max_bars is not None:
        events = events[:max_bars]

    print(f"Loaded {len(events)} {event_label} for {symbol}")
    engine.load_events(events)

    print("Running replay...")
    import time

    t0 = time.monotonic()
    await engine.run()
    t1 = time.monotonic()
    print(f"Replay engine done in {t1-t0:.2f}s")
    print("Draining event bus...")
    await bus.drain()
    t2 = time.monotonic()
    print(f"Event bus drained in {t2-t1:.2f}s")

    snap = bus.metrics.snapshot()
    print(
        f"Events published: {snap['total_published']}, "
        f"dispatched: {snap['total_dispatched']}, errors: {snap['total_errors']}"
    )
    print(f"By type: {snap['events_by_type']}")

    for strat in strategies:
        await strat.stop()
    for component in [risk, exec_engine, broker, pm, metrics]:
        await component.stop()
    await bus.stop()

    if journal:
        await journal.flush()
        count = await journal.count()
        journal.close()
        print(f"Journal records written: {count}")

    result = metrics.compute()
    print()
    print(f"{'='*50}")
    print(f"Backtest Results: {symbol}")
    print(f"{'='*50}")
    print(f"  Total Return:      {result.total_return:>+8.2%}")
    print(f"  Annualized Return: {result.annualized_return:>+8.2%}")
    print(f"  Sharpe Ratio:      {result.sharpe_ratio:>8.2f}")
    print(f"  Max Drawdown:      {result.max_drawdown:>8.2%}")
    print(f"  Win Rate:          {result.win_rate:>8.2%}")
    print(f"  Total Trades:      {result.total_trades:>8d}")
    print(f"  Winning Trades:    {result.winning_trades:>8d}")
    print(f"  Losing Trades:     {result.losing_trades:>8d}")
    print(f"  Turnover:          {result.turnover:>8.2f}x")
    print(f"  Start Equity:      ${result.start_equity:>8,.2f}")
    print(f"  End Equity:        ${result.end_equity:>8,.2f}")
    print(f"  Peak Equity:       ${result.peak_equity:>8,.2f}")
    print(f"{'='*50}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a backtest on CSV data")
    parser.add_argument("csv", help="Path to CSV file")
    parser.add_argument("--symbol", default="TSLA", help="Symbol name")
    parser.add_argument("--speed", type=float, default=1_000_000.0, help="Replay speed multiplier")
    parser.add_argument("--bars", type=int, default=None, help="Limit number of bars to process")
    parser.add_argument(
        "--journal", action="store_true", help="Enable SQLite event journal (temp file)"
    )
    parser.add_argument("--verbose", action="store_true", help="Show DEBUG level log output")
    parser.add_argument(
        "--tick", action="store_true", help="Tick-level replay (load tick CSV + VWAP strategy)"
    )
    args = parser.parse_args()
    asyncio.run(
        run_backtest(
            args.csv, args.symbol, args.speed, args.bars, args.journal, args.verbose, args.tick
        )
    )


if __name__ == "__main__":
    main()
