from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from trading_platform.events.bus import EventBus
from trading_platform.monitoring.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RuntimeSnapshot:
    queue_depth: int = 0
    subscriber_count: int = 0
    throughput_1m: float = 0.0
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
        self._samples: list[dict[str, Any]] = []
        self._last_published: int = 0
        self._last_sample_time: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._sample_loop())
        logger.info("metrics_collector_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("metrics_collector_stopped")

    def snapshot(self) -> RuntimeSnapshot:
        bus_metrics = self._event_bus.metrics.snapshot()

        throughput = self._compute_throughput()

        top_events = sorted(
            bus_metrics["events_by_type"].items(), key=lambda x: x[1], reverse=True
        )[:5]
        top_errors = sorted(
            bus_metrics["errors_by_type"].items(), key=lambda x: x[1], reverse=True
        )[:5]

        return RuntimeSnapshot(
            queue_depth=self._event_bus.queue_size,
            subscriber_count=self._event_bus.subscriber_count,
            throughput_1m=throughput,
            total_published=bus_metrics["total_published"],
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
            bus_metrics = self._event_bus.metrics.snapshot()
            sample = {
                "time": time.monotonic(),
                "total_published": bus_metrics["total_published"],
                "total_dispatched": bus_metrics["total_dispatched"],
                "total_errors": bus_metrics["total_errors"],
            }
            self._samples.append(sample)

            if len(self._samples) > 120:
                self._samples = self._samples[-60:]

            await asyncio.sleep(self._sample_interval)
