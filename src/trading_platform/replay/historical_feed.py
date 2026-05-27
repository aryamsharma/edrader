from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from trading_platform.events.event_types import BarCloseEvent
from trading_platform.monitoring.logging import get_logger

logger = get_logger(__name__)


class HistoricalFeed:
    def __init__(self) -> None:
        self._events: list[BarCloseEvent] = []

    @property
    def events(self) -> list[BarCloseEvent]:
        return list(self._events)

    @property
    def event_count(self) -> int:
        return len(self._events)

    def load_csv(
        self,
        path: str | Path,
        symbol: str,
        time_column: str = "time",
        open_column: str = "open",
        high_column: str = "high",
        low_column: str = "low",
        close_column: str = "close",
        volume_column: str = "volume",
        date_format: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[BarCloseEvent]:
        rows = self._read_csv(path)
        events: list[BarCloseEvent] = []

        for row in rows:
            ts = self._parse_time(row.get(time_column, ""), date_format)
            if ts is None:
                continue
            if start is not None and ts < start:
                continue
            if end is not None and ts > end:
                continue
            try:
                event = BarCloseEvent(
                    symbol=symbol,
                    timestamp=ts,
                    open=float(row.get(open_column, 0)),
                    high=float(row.get(high_column, 0)),
                    low=float(row.get(low_column, 0)),
                    close=float(row.get(close_column, 0)),
                    volume=int(float(row.get(volume_column, 0))),
                    source="historical_feed",
                )
            except (ValueError, TypeError):
                continue
            events.append(event)

        events.sort(key=lambda e: e.timestamp)
        self._events = events
        logger.info(
            "historical_feed_loaded",
            symbol=symbol,
            event_count=len(events),
            path=str(path),
        )
        return events

    def filter_by_date(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[BarCloseEvent]:
        result = self._events
        if start is not None:
            result = [e for e in result if e.timestamp >= start]
        if end is not None:
            result = [e for e in result if e.timestamp <= end]
        return result

    def clear(self) -> None:
        self._events.clear()

    def _read_csv(self, path: str | Path) -> list[dict[str, str]]:
        with open(path) as f:
            reader = csv.DictReader(f)
            return list(reader)

    def _parse_time(self, value: str, date_format: str | None) -> datetime | None:
        if not value:
            return None
        try:
            if date_format:
                from datetime import datetime as dt

                parsed = dt.strptime(value, date_format)
                return parsed.replace(tzinfo=UTC)
            return datetime.fromisoformat(value).replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return None
