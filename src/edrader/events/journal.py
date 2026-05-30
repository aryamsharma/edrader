from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

from edrader.events.event_types import BaseEvent


class Base(DeclarativeBase):
    pass


class EventRecord(Base):
    __tablename__ = "event_journal"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(128), nullable=False)
    event_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    payload = Column(Text, nullable=False)
    recorded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class EventJournal:
    def __init__(
        self,
        database_url: str,
        batch_size: int = 1,
        fast_mode: bool = False,
    ) -> None:
        self._engine = create_engine(database_url, echo=False)
        if fast_mode:
            with self._engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA synchronous = OFF")
                conn.exec_driver_sql("PRAGMA journal_mode = MEMORY")
                conn.exec_driver_sql("PRAGMA cache_size = -64000")
        Base.metadata.create_all(self._engine)
        self._sequence = 0
        self._initialized = False
        self._lock = asyncio.Lock()
        self._batch_size = batch_size
        self._buffer: list[EventRecord] = []

    def _ensure_sequence_sync(self) -> None:
        if self._initialized:
            return
        with Session(self._engine) as session:
            last = session.query(EventRecord).order_by(EventRecord.sequence.desc()).first()
            if last is not None:
                self._sequence = last.sequence  # type: ignore[assignment]
        self._initialized = True

    async def _ensure_sequence(self) -> None:
        await asyncio.to_thread(self._ensure_sequence_sync)

    async def append(self, event: BaseEvent) -> int:
        self._sequence += 1
        payload = json.dumps(event.to_dict(), default=str)
        record = EventRecord(
            sequence=self._sequence,
            event_type=type(event).__name__,
            event_id=event.event_id,
            timestamp=event.timestamp,
            payload=payload,
        )
        self._buffer.append(record)
        if self._batch_size > 0 and len(self._buffer) >= self._batch_size:
            batch = self._buffer
            self._buffer = []
            await asyncio.to_thread(self._flush_batch, self._engine, batch)
        return self._sequence

    @staticmethod
    def _flush_batch(engine: Engine, records: list[EventRecord]) -> None:
        now = datetime.now(UTC)
        rows = [
            {
                "sequence": r.sequence,
                "event_type": r.event_type,
                "event_id": r.event_id,
                "timestamp": r.timestamp,
                "payload": r.payload,
                "recorded_at": now,
            }
            for r in records
        ]
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO event_journal "
                    "(sequence, event_type, event_id, timestamp, payload, recorded_at) "
                    "VALUES (:sequence, :event_type, :event_id, :timestamp, :payload, :recorded_at)"
                ),
                rows,
            )

    async def replay(
        self,
        event_types: list[type[BaseEvent]] | None = None,
        since_sequence: int = 0,
        limit: int | None = None,
    ) -> list[BaseEvent]:
        await self._ensure_sequence()
        type_names: list[str] | None = [t.__name__ for t in event_types] if event_types else None

        def _do_query() -> list[BaseEvent]:
            with Session(self._engine) as session:
                query = session.query(EventRecord).filter(EventRecord.sequence > since_sequence)
                if type_names:
                    query = query.filter(EventRecord.event_type.in_(type_names))
                query = query.order_by(EventRecord.sequence.asc())
                if limit is not None:
                    query = query.limit(limit)
                records = query.all()

            events: list[BaseEvent] = []
            for record in records:
                payload = json.loads(record.payload)  # type: ignore[arg-type]
                event = BaseEvent.from_dict(payload)
                events.append(event)
            return events

        return await asyncio.to_thread(_do_query)

    async def count(self) -> int:
        await self._ensure_sequence()

        def _do_count() -> int:
            with Session(self._engine) as session:
                return session.query(EventRecord).count()

        return await asyncio.to_thread(_do_count)

    @property
    async def last_sequence(self) -> int:
        await self._ensure_sequence()
        return self._sequence

    async def flush(self) -> None:
        if not self._buffer:
            return
        batch = self._buffer
        self._buffer = []
        await asyncio.to_thread(self._flush_batch, self._engine, batch)

    def close(self) -> None:
        if self._buffer:
            self._flush_batch(self._engine, self._buffer)
            self._buffer = []
        self._engine.dispose()
