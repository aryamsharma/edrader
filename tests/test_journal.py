from __future__ import annotations

from pathlib import Path

import pytest

from edrader.events.event_types import (
    BaseEvent,
    HeartbeatEvent,
    MarketTickEvent,
    OrderFilledEvent,
    SignalGeneratedEvent,
)
from edrader.events.journal import EventJournal


@pytest.fixture
def journal(tmp_path: Path) -> EventJournal:
    db_path = tmp_path / "test_journal.db"
    return EventJournal(f"sqlite:///{db_path}")


@pytest.mark.asyncio
async def test_append_event(journal: EventJournal) -> None:
    event = MarketTickEvent(symbol="AAPL", price=150.0)
    seq = journal.append(event)
    assert seq == 1
    assert journal.count() == 1


@pytest.mark.asyncio
async def test_append_multiple_events(journal: EventJournal) -> None:
    journal.append(HeartbeatEvent())
    journal.append(MarketTickEvent(symbol="AAPL", price=150.0))
    journal.append(
        SignalGeneratedEvent(
            strategy_id="test",
            symbol="AAPL",
            side="BUY",
            confidence=0.8,
            suggested_size=100,
        )
    )
    assert journal.count() == 3
    assert journal.last_sequence == 3


@pytest.mark.asyncio
async def test_replay_all(journal: EventJournal) -> None:
    e1 = HeartbeatEvent()
    e2 = MarketTickEvent(symbol="AAPL", price=150.0)
    journal.append(e1)
    journal.append(e2)

    events = journal.replay()
    assert len(events) == 2
    assert events[0].event_id == e1.event_id
    assert events[1].event_id == e2.event_id


@pytest.mark.asyncio
async def test_replay_with_type_filter(journal: EventJournal) -> None:
    journal.append(HeartbeatEvent())
    journal.append(MarketTickEvent(symbol="AAPL", price=150.0))
    journal.append(HeartbeatEvent())

    events = journal.replay(event_types=[HeartbeatEvent])
    assert len(events) == 2
    assert all(isinstance(e, HeartbeatEvent) for e in events)


@pytest.mark.asyncio
async def test_replay_since_sequence(journal: EventJournal) -> None:
    journal.append(HeartbeatEvent())
    e2 = MarketTickEvent(symbol="AAPL", price=150.0)
    journal.append(e2)
    e3 = HeartbeatEvent()
    journal.append(e3)

    events = journal.replay(since_sequence=1)
    assert len(events) == 2
    assert events[0].event_id == e2.event_id
    assert events[1].event_id == e3.event_id


@pytest.mark.asyncio
async def test_replay_with_limit(journal: EventJournal) -> None:
    journal.append(HeartbeatEvent())
    journal.append(MarketTickEvent(symbol="AAPL", price=150.0))
    journal.append(HeartbeatEvent())

    events = journal.replay(limit=2)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_roundtrip_fidelity(journal: EventJournal) -> None:
    original = OrderFilledEvent(
        order_id="ORD-001",
        symbol="AAPL",
        side="BUY",
        fill_price=150.25,
        fill_quantity=100,
        source="test_module",
    )
    journal.append(original)

    events = journal.replay()
    restored = events[0]
    assert isinstance(restored, OrderFilledEvent)
    assert restored.order_id == "ORD-001"
    assert restored.fill_price == 150.25
    assert restored.fill_quantity == 100
    assert restored.source == "test_module"
    assert restored.event_id == original.event_id


@pytest.mark.asyncio
async def test_empty_journal(journal: EventJournal) -> None:
    assert journal.count() == 0
    events = journal.replay()
    assert len(events) == 0


@pytest.mark.asyncio
async def test_sequence_monotonic(journal: EventJournal) -> None:
    seq1 = journal.append(HeartbeatEvent())
    seq2 = journal.append(HeartbeatEvent())
    seq3 = journal.append(HeartbeatEvent())
    assert seq1 < seq2 < seq3


@pytest.mark.asyncio
async def test_journal_reuses_connection(journal: EventJournal) -> None:
    journal.append(HeartbeatEvent())
    journal.append(HeartbeatEvent())
    assert journal.count() == 2

    events = journal.replay()
    assert len(events) == 2


@pytest.mark.asyncio
async def test_close(journal: EventJournal) -> None:
    journal.append(HeartbeatEvent())
    journal.close()


@pytest.mark.asyncio
async def test_multiple_event_types_roundtrip(journal: EventJournal) -> None:
    events: list[BaseEvent] = [
        HeartbeatEvent(),
        MarketTickEvent(symbol="AAPL", price=150.0, source="test"),
        SignalGeneratedEvent(
            strategy_id="s1",
            symbol="AAPL",
            side="BUY",
            confidence=0.9,
            suggested_size=10,
        ),
        OrderFilledEvent(
            order_id="ORD-1",
            symbol="AAPL",
            side="BUY",
            fill_price=150.0,
            fill_quantity=10,
        ),
    ]
    for e in events:
        journal.append(e)

    replayed = journal.replay()
    assert len(replayed) == 4
    for original, restored in zip(events, replayed, strict=True):
        assert type(restored) is type(original)
        assert restored.event_id == original.event_id
        assert restored.to_dict() == original.to_dict()
