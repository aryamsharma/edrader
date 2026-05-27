from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from edrader.events.bus import EventBus
from edrader.events.event_types import BaseEvent, SignalGeneratedEvent
from edrader.monitoring.logging import get_logger

logger = get_logger(__name__)


class Strategy(ABC):
    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
    ) -> None:
        self._strategy_id = strategy_id
        self._event_bus = event_bus
        self._running = False
        self._subscriptions: list[Callable[[], None]] = []

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def is_running(self) -> bool:
        return self._running

    @abstractmethod
    async def on_event(self, event: BaseEvent) -> None: ...

    async def on_start(self) -> None:
        return None

    async def on_stop(self) -> None:
        return None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self._subscribe_to_events()
        await self.on_start()
        logger.info("strategy_started", strategy_id=self._strategy_id)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for unsub in self._subscriptions:
            unsub()
        self._subscriptions.clear()
        await self.on_stop()
        logger.info("strategy_stopped", strategy_id=self._strategy_id)

    def _subscribe(self, event_type: type[BaseEvent]) -> None:
        async def handler(event: BaseEvent) -> None:
            await self.on_event(event)

        self._event_bus.subscribe(event_type, handler, name=f"strategy_{self._strategy_id}")

        def _unsubscribe() -> None:
            self._event_bus.unsubscribe(event_type, handler)

        self._subscriptions.append(_unsubscribe)

    async def _subscribe_to_events(self) -> None:
        for event_type in self.event_types():
            self._subscribe(event_type)

    def event_types(self) -> list[type[BaseEvent]]:
        from edrader.events.event_types import BarCloseEvent

        return [BarCloseEvent]

    async def emit_signal(
        self,
        symbol: str,
        side: str,
        confidence: float,
        suggested_size: int,
    ) -> None:
        if not self._running:
            return
        await self._event_bus.publish(
            SignalGeneratedEvent(
                strategy_id=self._strategy_id,
                symbol=symbol,
                side=side,
                confidence=confidence,
                suggested_size=suggested_size,
                source=self._strategy_id,
            )
        )
        logger.info(
            "signal_emitted",
            strategy_id=self._strategy_id,
            symbol=symbol,
            side=side,
            confidence=confidence,
            suggested_size=suggested_size,
        )


class StrategyLoader:
    def __init__(self) -> None:
        self._registry: dict[str, type[Strategy]] = {}

    def register(self, strategy_id: str, strategy_class: type[Strategy]) -> None:
        if strategy_id in self._registry:
            raise ValueError(f"Strategy '{strategy_id}' already registered")
        self._registry[strategy_id] = strategy_class
        logger.info("strategy_registered", strategy_id=strategy_id, cls=strategy_class.__name__)

    def create(
        self,
        strategy_id: str,
        event_bus: EventBus,
        **kwargs: Any,
    ) -> Strategy:
        if strategy_id not in self._registry:
            raise KeyError(f"Unknown strategy '{strategy_id}'")
        cls = self._registry[strategy_id]
        instance = cls(strategy_id=strategy_id, event_bus=event_bus, **kwargs)
        logger.info("strategy_created", strategy_id=strategy_id)
        return instance

    @property
    def registered_ids(self) -> list[str]:
        return list(self._registry.keys())
