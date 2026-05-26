from __future__ import annotations

from pathlib import Path

from trading_platform.app.config import TradingConfig, load_config
from trading_platform.events.bus import EventBus
from trading_platform.monitoring.logging import get_logger, setup_logging

logger = get_logger(__name__)


class Application:
    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.event_bus = EventBus()
        self._running = False

    @classmethod
    def from_config_path(cls, path: Path) -> Application:
        config = load_config(path)
        return cls(config)

    async def startup(self) -> None:
        setup_logging(self.config.app.log_level)
        await self.event_bus.start()
        self._running = True
        logger.info(
            "application_started",
            environment=self.config.app.environment,
            name=self.config.app.name,
        )

    async def shutdown(self) -> None:
        await self.event_bus.stop()
        self._running = False
        logger.info("application_stopped")

    @property
    def is_running(self) -> bool:
        return self._running
