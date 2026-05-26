from datetime import datetime

import pytest

from trading_platform.events.event_types import (
    BarCloseEvent,
    BaseEvent,
    BrokerDisconnectedEvent,
    HeartbeatEvent,
    MarketTickEvent,
    OrderFilledEvent,
    RiskViolationEvent,
    SignalGeneratedEvent,
)


def test_base_event_has_timestamp() -> None:
    event = BaseEvent()
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo is not None


def test_base_event_immutable() -> None:
    event = BaseEvent()
    with pytest.raises(AttributeError):
        event.event_id = "new_id"  # type: ignore


def test_market_tick_event() -> None:
    event = MarketTickEvent(symbol="AAPL", price=150.25, volume=1000)
    assert event.symbol == "AAPL"
    assert event.price == 150.25
    assert event.volume == 1000
    assert event.priority.name == "NORMAL"


def test_bar_close_event() -> None:
    event = BarCloseEvent(
        symbol="SPY", open=450.0, high=455.0, low=449.0, close=454.0, volume=50000
    )
    assert event.symbol == "SPY"
    assert event.high == 455.0
    assert event.low == 449.0


def test_signal_generated_event() -> None:
    event = SignalGeneratedEvent(
        strategy_id="sma_cross",
        symbol="AAPL",
        side="BUY",
        confidence=0.85,
        suggested_size=100,
    )
    assert event.strategy_id == "sma_cross"
    assert event.side == "BUY"
    assert event.confidence == 0.85


def test_risk_violation_event() -> None:
    event = RiskViolationEvent(
        strategy_id="momentum", rule="max_position_size", reason="Exceeds 100 shares"
    )
    assert event.rule == "max_position_size"
    assert "100 shares" in event.reason


def test_order_filled_event() -> None:
    event = OrderFilledEvent(
        order_id="ORD-001",
        symbol="AAPL",
        side="BUY",
        fill_price=150.0,
        fill_quantity=100,
    )
    assert event.order_id == "ORD-001"
    assert event.fill_price == 150.0
    assert event.fill_quantity == 100


def test_broker_disconnected_event() -> None:
    event = BrokerDisconnectedEvent(reason="Connection timeout")
    assert "timeout" in event.reason


def test_heartbeat_event() -> None:
    event = HeartbeatEvent()
    assert isinstance(event.timestamp, datetime)
    assert event.priority.name == "NORMAL"


def test_event_equality_by_reference() -> None:
    e1 = MarketTickEvent(symbol="AAPL", price=150.0)
    e2 = MarketTickEvent(symbol="AAPL", price=150.0)
    assert e1 != e2  # different event_ids
