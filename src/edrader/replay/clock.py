from __future__ import annotations

from datetime import UTC, datetime, timedelta

from edrader.monitoring.logging import get_logger

logger = get_logger(__name__)


class ReplayClock:
    def __init__(self, start_time: datetime | None = None) -> None:
        self._base_time: datetime = start_time or datetime.now(UTC)
        self._elapsed: float = 0.0
        self._speed: float = 1.0
        self._paused: bool = False

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        if value <= 0:
            raise ValueError("Speed must be positive")
        self._speed = value

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def base_time(self) -> datetime:
        return self._base_time

    def now(self) -> datetime:
        if self._paused:
            return self._base_time
        return self._base_time + timedelta(seconds=self._elapsed * self._speed)

    def advance(self, seconds: float) -> None:
        if self._paused:
            return
        self._elapsed += seconds

    def set_time(self, dt: datetime) -> None:
        self._elapsed = 0.0
        self._base_time = dt

    def pause(self) -> None:
        self._paused = True
        logger.info("replay_clock_paused")

    def resume(self) -> None:
        self._paused = False
        self._base_time = self.now()
        self._elapsed = 0.0
        logger.info("replay_clock_resumed")

    def reset(self) -> None:
        self._elapsed = 0.0
        self.speed = 1.0
        self._paused = False
        logger.info("replay_clock_reset")
