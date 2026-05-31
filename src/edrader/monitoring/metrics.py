from __future__ import annotations

import asyncio
import contextlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from edrader.events.bus import EventBus
from edrader.events.event_types import BaseEvent
from edrader.monitoring.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RuntimeSnapshot:
    queue_depth: int = 0
    subscriber_count: int = 0
    throughput_1m: float = 0.0
    publish_rate: float = 0.0
    total_published: int = 0
    total_dispatched: int = 0
    total_errors: int = 0
    top_event_types: list[tuple[str, int]] = field(default_factory=list)
    top_error_types: list[tuple[str, int]] = field(default_factory=list)


class MetricsCollector:
    def __init__(
        self,
        event_bus: EventBus,
        sample_interval: float = 1.0,
    ) -> None:
        self._event_bus = event_bus
        self._sample_interval = sample_interval
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._active = False
        self._event_count: int = 0
        self._events_by_type: dict[str, int] = defaultdict(int)
        self._errors_by_type: dict[str, int] = defaultdict(int)
        self._samples: list[dict[str, Any]] = []

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._active = True

        async def handler(event: BaseEvent) -> None:
            if not self._active:
                return
            self._event_count += 1
            self._events_by_type[type(event).__name__] += 1

        self._event_bus.subscribe_all(handler, name="metrics_collector")
        self._task = asyncio.create_task(self._sample_loop())
        logger.info("metrics_collector_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._active = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("metrics_collector_stopped")

    def snapshot(self) -> RuntimeSnapshot:
        bus_metrics = self._event_bus.metrics.snapshot()

        throughput = self._compute_throughput()

        top_events = sorted(self._events_by_type.items(), key=lambda x: x[1], reverse=True)[:5]
        top_errors = sorted(self._errors_by_type.items(), key=lambda x: x[1], reverse=True)[:5]

        return RuntimeSnapshot(
            queue_depth=self._event_bus.queue_size,
            subscriber_count=self._event_bus.subscriber_count,
            throughput_1m=throughput,
            publish_rate=bus_metrics.get("publish_rate", 0.0),
            total_published=self._event_count,
            total_dispatched=bus_metrics["total_dispatched"],
            total_errors=bus_metrics["total_errors"],
            top_event_types=top_events,
            top_error_types=top_errors,
        )

    def _compute_throughput(self) -> float:
        now = time.monotonic()
        if not self._samples:
            return 0.0

        cutoff = now - 60.0
        recent = [s for s in self._samples if s["time"] >= cutoff]

        if len(recent) < 2:
            return 0.0

        first = recent[0]
        last = recent[-1]
        elapsed = last["time"] - first["time"]

        if elapsed <= 0:
            return 0.0

        published_delta = last["total_published"] - first["total_published"]
        return published_delta / elapsed  # type: ignore[no-any-return]

    async def _sample_loop(self) -> None:
        while self._running:
            sample = {
                "time": time.monotonic(),
                "total_published": self._event_count,
            }
            self._samples.append(sample)

            if len(self._samples) > 120:
                self._samples = self._samples[-60:]

            await asyncio.sleep(self._sample_interval)
