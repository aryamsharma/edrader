from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from trading_platform.events.event_types import BaseEvent


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
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url, echo=False)
        Base.metadata.create_all(self._engine)
        self._sequence = 0
        self._initialized = False

    def _ensure_sequence(self) -> None:
        if self._initialized:
            return
        with Session(self._engine) as session:
            last = session.query(EventRecord).order_by(EventRecord.sequence.desc()).first()
            if last is not None:
                self._sequence = last.sequence  # type: ignore[assignment]
        self._initialized = True

    def append(self, event: BaseEvent) -> int:
        self._ensure_sequence()
        self._sequence += 1
        payload = json.dumps(event.to_dict(), default=str)
        record = EventRecord(
            sequence=self._sequence,
            event_type=type(event).__name__,
            event_id=event.event_id,
            timestamp=event.timestamp,
            payload=payload,
        )
        with Session(self._engine) as session:
            session.add(record)
            session.commit()
        return self._sequence

    def replay(
        self,
        event_types: list[type[BaseEvent]] | None = None,
        since_sequence: int = 0,
        limit: int | None = None,
    ) -> list[BaseEvent]:
        self._ensure_sequence()
        type_names: list[str] | None = [t.__name__ for t in event_types] if event_types else None

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

    def count(self) -> int:
        self._ensure_sequence()
        with Session(self._engine) as session:
            return session.query(EventRecord).count()

    @property
    def last_sequence(self) -> int:
        self._ensure_sequence()
        return self._sequence

    def close(self) -> None:
        self._engine.dispose()
