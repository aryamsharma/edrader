from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

from trading_platform.events.event_types import BaseEvent

AsyncHandler = Callable[[BaseEvent], Coroutine[Any, Any, None]]


class EventBus:
    def __init__(self, max_queue_size: int = 10_000) -> None:
        self._queue: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=max_queue_size)
        self._subscribers: dict[type[BaseEvent], list[AsyncHandler]] = defaultdict(list)
        self._running = False
        self._task: asyncio.Task[None] | None = None

    def subscribe(self, event_type: type[BaseEvent], handler: AsyncHandler) -> None:
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: type[BaseEvent], handler: AsyncHandler) -> None:
        self._subscribers[event_type].remove(handler)
        if not self._subscribers[event_type]:
            del self._subscribers[event_type]

    async def publish(self, event: BaseEvent) -> None:
        await self._queue.put(event)

    async def _dispatch(self, event: BaseEvent) -> None:
        handlers = self._subscribers.get(type(event), [])
        if not handlers:
            return
        results = await asyncio.gather(
            *[handler(event) for handler in handlers],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                pass

    async def _process_events(self) -> None:
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._dispatch(event)
                self._queue.task_done()
            except TimeoutError:
                continue

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._process_events())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()
