from __future__ import annotations

import asyncio

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import BaseEvent
from trading_platform.monitoring.logging import get_logger
from trading_platform.replay.clock import ReplayClock

logger = get_logger(__name__)


class ReplayEngine:
    def __init__(
        self,
        event_bus: EventBus,
        clock: ReplayClock | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._clock = clock or ReplayClock()
        self._events: list[BaseEvent] = []
        self._index: int = 0
        self._running = False
        self._paused = False
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def total_events(self) -> int:
        return len(self._events)

    @property
    def clock(self) -> ReplayClock:
        return self._clock

    def load_events(self, events: list[BaseEvent]) -> None:
        sorted_events = sorted(events, key=lambda e: e.timestamp)
        self._events = sorted_events
        self._index = 0
        if sorted_events:
            self._clock.set_time(sorted_events[0].timestamp)
        logger.info("replay_events_loaded", count=len(sorted_events))

    async def run(self) -> None:
        if self._running:
            return
        self._running = True
        self._paused = False
        try:
            while self._index < len(self._events) and self._running:
                if self._paused:
                    await asyncio.sleep(0.1)
                    continue
                event = self._events[self._index]
                await self._publish_event(event)
                self._index += 1
                if self._index < len(self._events):
                    await self._wait_for_next(event, self._events[self._index])
            logger.info("replay_completed", events_played=self._index)
        finally:
            self._running = False

    async def step(self) -> bool:
        if self._index >= len(self._events):
            return False
        event = self._events[self._index]
        await self._publish_event(event)
        self._index += 1
        return True

    def pause(self) -> None:
        self._paused = True
        self._clock.pause()
        logger.info("replay_paused")

    def resume(self) -> None:
        self._paused = False
        self._clock.resume()
        logger.info("replay_resumed")

    def stop(self) -> None:
        self._running = False
        logger.info("replay_stopped")

    async def _publish_event(self, event: BaseEvent) -> None:
        self._clock.set_time(event.timestamp)
        await self._event_bus.publish(event)
        logger.debug("replay_event_published", index=self._index, event_type=type(event).__name__)

    async def _wait_for_next(self, current: BaseEvent, next_event: BaseEvent) -> None:
        delta = (next_event.timestamp - current.timestamp).total_seconds()
        if delta <= 0:
            return
        adjusted = delta / self._clock.speed
        await asyncio.sleep(adjusted)
