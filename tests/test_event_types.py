from __future__ import annotations

from datetime import datetime

import pytest

from edrader.events.event_types import (
    AccountSummaryUpdate,
    BarCloseEvent,
    BaseEvent,
    BrokerDisconnectedEvent,
    EventPriority,
    ExposureLimitEvent,
    HeartbeatEvent,
    MarketCloseEvent,
    MarketOpenEvent,
    MarketTickEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    OrderRequestedEvent,
    OrderStatusChangedEvent,
    OrderSubmittedEvent,
    PnLUpdatedEvent,
    PositionClosedEvent,
    PositionOpenedEvent,
    PositionUpdate,
    RiskViolationEvent,
    SignalGeneratedEvent,
    SignalRejectedEvent,
    StrategyErrorEvent,
    TradingHaltedEvent,
)


def test_base_event_generates_id() -> None:
    event = BaseEvent()
    assert len(event.event_id) > 0
    assert isinstance(event.event_id, str)
    assert "-" in event.event_id  # hostname-pid-counter format


def test_base_event_has_timestamp() -> None:
    event = BaseEvent()
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo is not None


def test_base_event_immutable() -> None:
    event = BaseEvent()
    with pytest.raises(AttributeError):
        event.event_id = "new_id"  # type: ignore


def test_base_event_default_priority() -> None:
    event = BaseEvent()
    assert event.priority == EventPriority.NORMAL


def test_base_event_with_source() -> None:
    event = BaseEvent(source="test_module")
    assert event.source == "test_module"


def test_base_event_with_correlation_id() -> None:
    event = BaseEvent(correlation_id="chain-001")
    assert event.correlation_id == "chain-001"


def test_to_dict_roundtrip() -> None:
    original = MarketTickEvent(
        symbol="AAPL",
        price=150.25,
        volume=1000,
        bid=150.20,
        ask=150.30,
        source="test",
    )
    data = original.to_dict()
    assert data["event_type"] == "MarketTickEvent"
    assert data["symbol"] == "AAPL"
    assert data["price"] == 150.25
    assert data["source"] == "test"

    restored = BaseEvent.from_dict(data)
    assert isinstance(restored, MarketTickEvent)
    assert restored.symbol == "AAPL"
    assert restored.price == 150.25
    assert restored.event_id == original.event_id
    assert restored.source == "test"


def test_to_dict_includes_base_fields() -> None:
    event = HeartbeatEvent(priority=EventPriority.HIGH)
    data = event.to_dict()
    assert data["event_type"] == "HeartbeatEvent"
    assert data["priority"] == "HIGH"
    assert "timestamp" in data
    assert "event_id" in data
    assert "correlation_id" in data
    assert "source" in data


def test_from_dict_restores_priority() -> None:
    data = {
        "event_type": "HeartbeatEvent",
        "event_id": "abc123",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "priority": "CRITICAL",
        "correlation_id": "",
        "source": "",
    }
    event = BaseEvent.from_dict(data)
    assert event.priority == EventPriority.CRITICAL


def test_market_tick_event() -> None:
    event = MarketTickEvent(symbol="AAPL", price=150.25, volume=1000)
    assert event.symbol == "AAPL"
    assert event.price == 150.25
    assert event.volume == 1000


def test_bar_close_event() -> None:
    event = BarCloseEvent(
        symbol="SPY", open=450.0, high=455.0, low=449.0, close=454.0, volume=50000
    )
    assert event.high == 455.0


def test_market_open_event() -> None:
    event = MarketOpenEvent(symbol="SPY")
    assert event.symbol == "SPY"


def test_market_close_event() -> None:
    event = MarketCloseEvent(symbol="SPY")
    assert event.symbol == "SPY"


def test_signal_generated_event() -> None:
    event = SignalGeneratedEvent(
        strategy_id="sma_cross",
        symbol="AAPL",
        side="BUY",
        confidence=0.85,
        suggested_size=100,
    )
    assert event.side == "BUY"
    assert event.confidence == 0.85


def test_signal_rejected_event() -> None:
    event = SignalRejectedEvent(strategy_id="sma_cross", symbol="AAPL", reason="low_confidence")
    assert event.reason == "low_confidence"


def test_strategy_error_event() -> None:
    event = StrategyErrorEvent(strategy_id="momentum", error="division by zero")
    assert "division" in event.error


def test_risk_violation_event() -> None:
    event = RiskViolationEvent(
        strategy_id="momentum", rule="max_position_size", reason="Exceeds 100 shares"
    )
    assert event.rule == "max_position_size"


def test_trading_halted_event() -> None:
    event = TradingHaltedEvent(reason="max_daily_loss")
    assert event.reason == "max_daily_loss"


def test_exposure_limit_event() -> None:
    event = ExposureLimitEvent(current_exposure=75000.0, limit=50000.0)
    assert event.current_exposure == 75000.0
    assert event.limit == 50000.0


def test_order_requested_event() -> None:
    event = OrderRequestedEvent(
        symbol="AAPL", side="BUY", quantity=100, order_type="LIMIT", limit_price=150.0
    )
    assert event.order_type == "LIMIT"
    assert event.limit_price == 150.0


def test_order_submitted_event() -> None:
    event = OrderSubmittedEvent(
        order_id="ORD-001",
        symbol="AAPL",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        limit_price=150.0,
    )
    assert event.order_id == "ORD-001"
    assert event.limit_price == 150.0


def test_order_filled_event() -> None:
    event = OrderFilledEvent(
        order_id="ORD-001",
        symbol="AAPL",
        side="BUY",
        fill_price=150.0,
        fill_quantity=100,
    )
    assert event.fill_price == 150.0


def test_order_cancelled_event() -> None:
    event = OrderCancelledEvent(order_id="ORD-001", reason="manual")
    assert event.reason == "manual"


def test_order_status_changed_event() -> None:
    event = OrderStatusChangedEvent(order_id="ORD-001", status="Filled")
    assert event.status == "Filled"


def test_position_opened_event() -> None:
    event = PositionOpenedEvent(symbol="AAPL", quantity=100, avg_cost=150.0)
    assert event.avg_cost == 150.0


def test_position_closed_event() -> None:
    event = PositionClosedEvent(symbol="AAPL", realized_pnl=500.0)
    assert event.realized_pnl == 500.0


def test_pnl_updated_event() -> None:
    event = PnLUpdatedEvent(symbol="AAPL", unrealized_pnl=250.0, realized_pnl=500.0)
    assert event.unrealized_pnl == 250.0
    assert event.realized_pnl == 500.0


def test_account_summary_update() -> None:
    event = AccountSummaryUpdate(
        cash=100000.0, buying_power=200000.0, gross_position_value=50000.0, net_liquidation=150000.0
    )
    assert event.cash == 100000.0
    assert event.buying_power == 200000.0


def test_position_update() -> None:
    event = PositionUpdate(symbol="AAPL", position=100, avg_cost=150.0, market_price=155.0)
    assert event.position == 100
    assert event.market_price == 155.0


def test_broker_disconnected_event() -> None:
    event = BrokerDisconnectedEvent(reason="Connection timeout")
    assert "timeout" in event.reason


def test_heartbeat_event() -> None:
    event = HeartbeatEvent()
    assert isinstance(event.timestamp, datetime)


def test_event_equality_by_reference() -> None:
    e1 = MarketTickEvent(symbol="AAPL", price=150.0)
    e2 = MarketTickEvent(symbol="AAPL", price=150.0)
    assert e1 != e2  # different event_ids


def test_to_dict_preserves_none() -> None:
    event = OrderSubmittedEvent(
        order_id="ORD-001", symbol="AAPL", side="BUY", quantity=100, order_type="MARKET"
    )
    data = event.to_dict()
    assert data["limit_price"] is None


def test_to_dict_custom_priority() -> None:
    event = RiskViolationEvent(
        strategy_id="test",
        rule="max_daily_loss",
        reason="exceeded",
        priority=EventPriority.HIGH,
    )
    data = event.to_dict()
    assert data["priority"] == "HIGH"


def test_from_dict_unknown_type_falls_back() -> None:
    data = {
        "event_type": "NonExistentEvent",
        "event_id": "abc",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "priority": "NORMAL",
        "correlation_id": "",
        "source": "",
    }
    event = BaseEvent.from_dict(data)
    assert isinstance(event, BaseEvent)
