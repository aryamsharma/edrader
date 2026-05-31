from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from edrader.app.config import TradingConfig, load_config
from edrader.events.bus import EventBus
from edrader.events.event_types import BaseEvent
from edrader.events.journal import EventJournal
from edrader.execution.engine import ExecutionEngine
from edrader.monitoring.alerts import AlertManager
from edrader.monitoring.logging import get_logger, setup_logging
from edrader.monitoring.metrics import MetricsCollector
from edrader.portfolio.position import PositionManager
from edrader.risk.engine import RiskEngine
from edrader.strategies.base import StrategyLoader
from edrader.strategies.examples.mean_reversion import MeanReversionStrategy
from edrader.strategies.examples.sma_crossover import SmaCrossoverStrategy

logger = get_logger(__name__)

LIVE_COMPONENTS = "live_components"
SIMULATED_COMPONENTS = "simulated_components"
MONITORING_COMPONENTS = "monitoring_components"


class Application:
    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.event_bus = EventBus()
        self._running = False
        self._components: dict[str, list[Any]] = {}
        self._journal: EventJournal | None = None
        self._strategy_loader: StrategyLoader | None = None
        self._strategies: list[Any] = []
        self._replay_task: asyncio.Task[None] | None = None

    @classmethod
    def from_config_path(cls, path: Path) -> Application:
        config = load_config(path)
        return cls(config)

    def _build_live_components(self) -> list[Any]:
        components: list[Any] = []

        from ib_async import IB

        from edrader.broker.ibkr_client import IBKRClient
        from edrader.broker.market_data import MarketDataFeed
        from edrader.broker.order_management import BrokerAdapter

        ib = IB()  # type: ignore[no-untyped-call]
        ibkr = IBKRClient(config=self.config.broker, event_bus=self.event_bus, ib=ib)
        feed = MarketDataFeed(ib=ib, event_bus=self.event_bus)
        adapter = BrokerAdapter(ib=ib, event_bus=self.event_bus)

        components.append(ibkr)
        components.append(feed)
        components.append(adapter)
        return components

    def _build_simulated_components(self) -> list[Any]:
        from edrader.replay.simulated_broker import SimulatedBroker

        broker = SimulatedBroker(event_bus=self.event_bus)
        return [broker]

    def _build_replay(self) -> None:
        from edrader.replay.clock import ReplayClock
        from edrader.replay.engine import ReplayEngine
        from edrader.replay.historical_feed import HistoricalFeed

        clock = ReplayClock()
        feed = HistoricalFeed()
        replay = ReplayEngine(event_bus=self.event_bus, clock=clock)

        data_dir = Path("data")
        if data_dir.exists():
            for csv_path in sorted(data_dir.glob("*.csv")):
                symbol = csv_path.stem
                events = feed.load_csv(csv_path, symbol=symbol)
                if events:
                    replay.load_events(events)
                    logger.info(
                        "loaded_csv_data", symbol=symbol, path=str(csv_path), count=len(events)
                    )

        if replay.total_events > 0:
            self._replay_task = asyncio.create_task(replay.run())

    def _build_monitoring_components(self) -> list[Any]:
        pm = PositionManager(event_bus=self.event_bus)
        risk = RiskEngine(event_bus=self.event_bus, position_manager=pm)
        exec_eng = ExecutionEngine(
            event_bus=self.event_bus,
            default_order_type=self.config.execution.default_order_type,
            throttle_delay=self.config.execution.throttle_delay,
        )
        metrics = MetricsCollector(event_bus=self.event_bus)
        alerts = AlertManager(event_bus=self.event_bus)
        return [risk, exec_eng, pm, metrics, alerts]

    def _wire_journal(self) -> None:
        db_url = self.config.persistence.database_url
        self._journal = EventJournal(database_url=db_url)

        async def journal_handler(event: BaseEvent) -> None:
            if self._journal is not None:
                await self._journal.append(event)

        self.event_bus.subscribe_all(journal_handler, name="journal")

    def _wire_strategies(self) -> None:
        self._strategy_loader = StrategyLoader()
        self._strategy_loader.register("sma_crossover", SmaCrossoverStrategy)
        self._strategy_loader.register("mean_reversion", MeanReversionStrategy)

    async def _start_strategies(self) -> None:
        assert self._strategy_loader is not None
        sma = self._strategy_loader.create(
            "sma_crossover", event_bus=self.event_bus, default_size=100
        )
        mr = self._strategy_loader.create(
            "mean_reversion", event_bus=self.event_bus, default_size=100
        )
        await sma.start()
        await mr.start()
        self._strategies = [sma, mr]

    async def _stop_strategies(self) -> None:
        for s in reversed(self._strategies):
            await s.stop()
        self._strategies.clear()

    async def _start_components(self, components: list[Any]) -> None:
        for c in components:
            await c.start()

    async def _stop_components(self, components: list[Any]) -> None:
        for c in reversed(components):
            await c.stop()

    async def startup(self) -> None:
        setup_logging(self.config.app.log_level)
        await self.event_bus.start()

        env = self.config.app.environment

        if env in ("paper", "live"):
            live = self._build_live_components()
            self._components[LIVE_COMPONENTS] = live
            await self._start_components(live)

            feed = live[1]
            for symbol in self.config.app.symbols:
                await feed.subscribe_symbol(symbol)

            from edrader.events.event_types import MarketTickEvent

            async def log_tick(ev: BaseEvent) -> None:
                if isinstance(ev, MarketTickEvent):
                    logger.info(
                        "market_tick",
                        symbol=ev.symbol,
                        price=ev.price,
                        volume=ev.volume,
                        bid=ev.bid,
                        ask=ev.ask,
                    )

            if self.config.app.symbols:
                self.event_bus.subscribe(MarketTickEvent, log_tick, name="tick_logger")
        else:
            sim = self._build_simulated_components()
            self._components[SIMULATED_COMPONENTS] = sim
            await self._start_components(sim)
            self._build_replay()

        monitoring = self._build_monitoring_components()
        self._components[MONITORING_COMPONENTS] = monitoring
        await self._start_components(monitoring)

        self._wire_journal()
        if self.config.app.strategies_enabled:
            self._wire_strategies()
            await self._start_strategies()

        self._running = True
        logger.info(
            "application_started",
            environment=env,
            name=self.config.app.name,
        )

    async def shutdown(self) -> None:
        self._running = False

        if self._replay_task is not None:
            self._replay_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await self._replay_task
            self._replay_task = None

        if self._strategies:
            await self._stop_strategies()

        for group_key in (MONITORING_COMPONENTS, SIMULATED_COMPONENTS, LIVE_COMPONENTS):
            group = self._components.pop(group_key, None)
            if group is not None:
                await self._stop_components(group)

        if self._journal is not None:
            self._journal.close()

        await self.event_bus.stop()
        logger.info("application_stopped")

    @property
    def is_running(self) -> bool:
        return self._running
