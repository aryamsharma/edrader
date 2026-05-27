from __future__ import annotations

from pathlib import Path
from typing import Any

from trading_platform.app.config import TradingConfig, load_config
from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import BaseEvent
from trading_platform.events.journal import EventJournal
from trading_platform.execution.engine import ExecutionEngine
from trading_platform.monitoring.alerts import AlertManager
from trading_platform.monitoring.logging import get_logger, setup_logging
from trading_platform.monitoring.metrics import MetricsCollector
from trading_platform.portfolio.position import PositionManager
from trading_platform.risk.engine import RiskEngine
from trading_platform.strategies.base import StrategyLoader
from trading_platform.strategies.examples.mean_reversion import MeanReversionStrategy
from trading_platform.strategies.examples.sma_crossover import SmaCrossoverStrategy

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

    @classmethod
    def from_config_path(cls, path: Path) -> Application:
        config = load_config(path)
        return cls(config)

    def _build_live_components(self) -> list[Any]:
        components: list[Any] = []

        from ib_insync import IB

        from trading_platform.broker.ibkr_client import IBKRClient
        from trading_platform.broker.market_data import MarketDataFeed
        from trading_platform.broker.order_management import BrokerAdapter

        ib = IB()  # type: ignore[no-untyped-call]
        ibkr = IBKRClient(config=self.config.broker, event_bus=self.event_bus, ib=ib)
        feed = MarketDataFeed(ib=ib, event_bus=self.event_bus)
        adapter = BrokerAdapter(ib=ib, event_bus=self.event_bus)

        components.append(ibkr)
        components.append(feed)
        components.append(adapter)
        return components

    def _build_simulated_components(self) -> list[Any]:
        from trading_platform.replay.simulated_broker import SimulatedBroker

        broker = SimulatedBroker(event_bus=self.event_bus)
        return [broker]

    def _build_monitoring_components(self) -> list[Any]:
        risk = RiskEngine(event_bus=self.event_bus)
        exec_eng = ExecutionEngine(
            event_bus=self.event_bus,
            default_order_type=self.config.execution.default_order_type,
            throttle_delay=self.config.execution.throttle_delay,
        )
        pm = PositionManager(event_bus=self.event_bus)
        metrics = MetricsCollector(event_bus=self.event_bus)
        alerts = AlertManager(event_bus=self.event_bus)
        return [risk, exec_eng, pm, metrics, alerts]

    def _wire_journal(self) -> None:
        db_url = self.config.persistence.database_url
        self._journal = EventJournal(database_url=db_url)

        async def journal_handler(event: BaseEvent) -> None:
            if self._journal is not None:
                self._journal.append(event)

        self.event_bus.subscribe_all(journal_handler, name="journal")

    def _wire_strategies(self) -> None:
        self._strategy_loader = StrategyLoader()
        self._strategy_loader.register("sma_crossover", SmaCrossoverStrategy)
        self._strategy_loader.register("mean_reversion", MeanReversionStrategy)

    async def _start_strategies(self) -> None:
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
        else:
            sim = self._build_simulated_components()
            self._components[SIMULATED_COMPONENTS] = sim
            await self._start_components(sim)

        monitoring = self._build_monitoring_components()
        self._components[MONITORING_COMPONENTS] = monitoring
        await self._start_components(monitoring)

        self._wire_journal()
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
