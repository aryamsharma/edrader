from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

from trading_platform.events.event_types import BaseEvent, EventPriority
from trading_platform.monitoring.logging import get_logger

logger = get_logger(__name__)

AsyncHandler = Callable[[BaseEvent], Coroutine[Any, Any, None]]
ErrorHandler = Callable[[BaseEvent, Exception], None]
EventFilter = Callable[[BaseEvent], bool]


class DispatchMetrics:
    def __init__(self) -> None:
        self.total_published: int = 0
        self.total_dispatched: int = 0
        self.total_errors: int = 0
        self.events_by_type: dict[str, int] = defaultdict(int)
        self.errors_by_type: dict[str, int] = defaultdict(int)

    def snapshot(self) -> dict[str, Any]:
        return {
            "total_published": self.total_published,
            "total_dispatched": self.total_dispatched,
            "total_errors": self.total_errors,
            "events_by_type": dict(self.events_by_type),
            "errors_by_type": dict(self.errors_by_type),
        }


class PriorityQueue:
    def __init__(self, maxsize: int = 10_000) -> None:
        self._normal: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=maxsize)
        self._high: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=maxsize)
        self._last_source: asyncio.Queue[BaseEvent] | None = None

    async def put(self, event: BaseEvent) -> None:
        if event.priority in (EventPriority.HIGH, EventPriority.CRITICAL):
            await self._high.put(event)
        else:
            await self._normal.put(event)

    async def get(self) -> BaseEvent:
        for q in (self._high, self._normal):
            try:
                event = await asyncio.wait_for(q.get(), timeout=0.01)
                self._last_source = q
                return event
            except TimeoutError:
                continue
        raise TimeoutError("no events available")

    def task_done(self) -> None:
        if self._last_source is not None:
            self._last_source.task_done()
            self._last_source = None

    def qsize(self) -> int:
        return self._high.qsize() + self._normal.qsize()

    async def join(self) -> None:
        await asyncio.gather(self._high.join(), self._normal.join())

    @property
    def high_size(self) -> int:
        return self._high.qsize()

    @property
    def normal_size(self) -> int:
        return self._normal.qsize()


class SubscriberEntry:
    def __init__(
        self,
        handler: AsyncHandler,
        event_filter: EventFilter | None = None,
        name: str = "",
    ) -> None:
        self.handler = handler
        self.event_filter = event_filter
        self.name = name or getattr(handler, "__name__", "unknown")


class EventBus:
    def __init__(
        self,
        max_queue_size: int = 10_000,
        error_handler: ErrorHandler | None = None,
    ) -> None:
        self._queue = PriorityQueue(maxsize=max_queue_size)
        self._subscribers: dict[type[BaseEvent], list[SubscriberEntry]] = defaultdict(list)
        self._wildcard_subscribers: list[SubscriberEntry] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._error_handler = error_handler
        self.metrics = DispatchMetrics()

    def subscribe(
        self,
        event_type: type[BaseEvent],
        handler: AsyncHandler,
        event_filter: EventFilter | None = None,
        name: str = "",
    ) -> None:
        entry = SubscriberEntry(handler, event_filter, name)
        self._subscribers[event_type].append(entry)

    def subscribe_all(
        self,
        handler: AsyncHandler,
        event_filter: EventFilter | None = None,
        name: str = "",
    ) -> None:
        entry = SubscriberEntry(handler, event_filter, name)
        self._wildcard_subscribers.append(entry)

    def unsubscribe(self, event_type: type[BaseEvent], handler: AsyncHandler) -> None:
        self._subscribers[event_type] = [
            e for e in self._subscribers[event_type] if e.handler is not handler
        ]
        if not self._subscribers[event_type]:
            del self._subscribers[event_type]

    async def publish(self, event: BaseEvent) -> None:
        self.metrics.total_published += 1
        type_name = type(event).__name__
        self.metrics.events_by_type[type_name] += 1
        await self._queue.put(event)

    async def _dispatch(self, event: BaseEvent) -> None:
        handlers: list[SubscriberEntry] = []

        handlers.extend(self._subscribers.get(type(event), []))
        handlers.extend(self._wildcard_subscribers)

        if not handlers:
            return

        for entry in handlers:
            if entry.event_filter is not None and not entry.event_filter(event):
                continue

            self.metrics.total_dispatched += 1
            try:
                await entry.handler(event)
            except Exception as exc:
                self.metrics.total_errors += 1
                type_name = type(event).__name__
                self.metrics.errors_by_type[type_name] += 1
                logger.error(
                    "dispatch_error",
                    handler=entry.name,
                    event_id=event.event_id,
                    event_type=type_name,
                    error=str(exc),
                )
                if self._error_handler is not None:
                    self._error_handler(event, exc)

    async def _process_events(self) -> None:
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                await self._dispatch(event)
                self._queue.task_done()
            except TimeoutError:
                continue

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_events())
        logger.info("event_bus_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("event_bus_stopped")

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def subscriber_count(self) -> int:
        return sum(len(v) for v in self._subscribers.values()) + len(self._wildcard_subscribers)

    def subscriber_count_for(self, event_type: type[BaseEvent]) -> int:
        return len(self._subscribers.get(event_type, []))
