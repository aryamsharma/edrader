from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from trading_platform.broker.order_management import BrokerAdapter
from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    OrderCancelledEvent,
    OrderFilledEvent,
    OrderRequestedEvent,
    OrderStatusChangedEvent,
    OrderSubmittedEvent,
)


def _make_trade(
    order_id: int = 1,
    symbol: str = "AAPL",
    side: str = "BUY",
    quantity: int = 100,
    order_type: str = "MKT",
    limit_price: float | None = None,
    status: str = "Submitted",
) -> MagicMock:
    trade = MagicMock()
    trade.order.orderId = order_id
    trade.order.action = side
    trade.order.totalQuantity = quantity
    trade.order.orderType = order_type
    trade.order.lmtPrice = limit_price
    trade.orderStatus.status = status
    trade.contract.symbol = symbol
    return trade


def _make_fill(
    symbol: str = "AAPL",
    side: str = "BUY",
    price: float = 150.25,
    shares: int = 100,
) -> MagicMock:
    fill = MagicMock()
    fill.execution.symbol = symbol
    fill.execution.side = side
    fill.execution.price = price
    fill.execution.shares = shares
    return fill


@pytest.fixture
def mock_ib() -> MagicMock:
    ib = MagicMock()
    ib.placeOrder = MagicMock()
    ib.cancelOrder = MagicMock()
    ib.orderStatusEvent = MagicMock()
    ib.orderStatusEvent.connect = MagicMock(return_value="os_handler")
    ib.orderStatusEvent.disconnect = MagicMock()
    ib.execDetailsEvent = MagicMock()
    ib.execDetailsEvent.connect = MagicMock(return_value="ed_handler")
    ib.execDetailsEvent.disconnect = MagicMock()
    return ib


@pytest.fixture
async def event_bus() -> EventBus:
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
def collected_events(event_bus: EventBus) -> list:
    events: list = []

    async def collector(event: object) -> None:
        events.append(event)

    event_bus.subscribe_all(collector, name="collector")
    return events


@pytest.fixture
async def adapter(
    mock_ib: MagicMock,
    event_bus: EventBus,
) -> BrokerAdapter:
    a = BrokerAdapter(ib=mock_ib, event_bus=event_bus)
    yield a
    if a.is_running:
        await a.stop()


class TestBrokerAdapterLifecycle:
    async def test_initial_state(self, adapter: BrokerAdapter) -> None:
        assert adapter.is_running is False
        assert adapter.active_order_ids == []

    async def test_start_sets_running(self, adapter: BrokerAdapter) -> None:
        await adapter.start()
        assert adapter.is_running is True

    async def test_stop_clears_running(self, adapter: BrokerAdapter) -> None:
        await adapter.start()
        await adapter.stop()
        assert adapter.is_running is False
        assert adapter.active_order_ids == []

    async def test_start_connects_handlers(
        self, adapter: BrokerAdapter, mock_ib: MagicMock
    ) -> None:
        await adapter.start()
        mock_ib.orderStatusEvent.connect.assert_called_once()
        mock_ib.execDetailsEvent.connect.assert_called_once()

    async def test_stop_disconnects_handlers(
        self, adapter: BrokerAdapter, mock_ib: MagicMock
    ) -> None:
        await adapter.start()
        await adapter.stop()
        mock_ib.orderStatusEvent.disconnect.assert_called_once_with("os_handler")
        mock_ib.execDetailsEvent.disconnect.assert_called_once_with("ed_handler")

    async def test_start_idempotent(self, adapter: BrokerAdapter) -> None:
        await adapter.start()
        await adapter.start()
        assert adapter.is_running is True

    async def test_stop_idempotent(self, adapter: BrokerAdapter) -> None:
        await adapter.start()
        await adapter.stop()
        await adapter.stop()
        assert adapter.is_running is False

    async def test_start_subscribes_to_order_requests(
        self, adapter: BrokerAdapter, event_bus: EventBus
    ) -> None:
        await adapter.start()
        count = event_bus.subscriber_count_for(OrderRequestedEvent)
        assert count == 1


class TestBrokerAdapterPlaceOrder:
    async def test_place_order_returns_order_id(
        self, adapter: BrokerAdapter, mock_ib: MagicMock
    ) -> None:
        await adapter.start()
        trade = _make_trade(order_id=42, symbol="AAPL", side="BUY", quantity=100)
        mock_ib.placeOrder.return_value = trade

        order_id = await adapter.place_order("AAPL", "BUY", 100)

        assert order_id == "42"
        assert adapter.active_order_ids == ["42"]

    async def test_place_order_calls_ib(self, adapter: BrokerAdapter, mock_ib: MagicMock) -> None:
        await adapter.start()
        trade = _make_trade(order_id=1)
        mock_ib.placeOrder.return_value = trade

        await adapter.place_order("AAPL", "BUY", 100)

        mock_ib.placeOrder.assert_called_once()
        args, _ = mock_ib.placeOrder.call_args
        contract = args[0]
        order = args[1]
        assert contract.symbol == "AAPL"
        assert order.action == "BUY"
        assert order.totalQuantity == 100
        assert order.orderType == "MKT"

    async def test_place_order_emits_submitted_event(
        self,
        adapter: BrokerAdapter,
        mock_ib: MagicMock,
        collected_events: list,
        event_bus: EventBus,
    ) -> None:
        await adapter.start()
        trade = _make_trade(order_id=42, symbol="AAPL", side="BUY", quantity=100)
        mock_ib.placeOrder.return_value = trade

        await adapter.place_order("AAPL", "BUY", 100)
        await event_bus.drain()

        submitted = [e for e in collected_events if isinstance(e, OrderSubmittedEvent)]
        assert len(submitted) == 1
        assert submitted[0].order_id == "42"
        assert submitted[0].symbol == "AAPL"
        assert submitted[0].side == "BUY"
        assert submitted[0].quantity == 100
        assert submitted[0].order_type == "MKT"
        assert submitted[0].source == "broker_adapter"

    async def test_place_order_with_limit_price(
        self, adapter: BrokerAdapter, mock_ib: MagicMock
    ) -> None:
        await adapter.start()
        trade = _make_trade(
            order_id=3, side="SELL", quantity=50, order_type="LMT", limit_price=155.0
        )
        mock_ib.placeOrder.return_value = trade

        await adapter.place_order("AAPL", "SELL", 50, order_type="LMT", limit_price=155.0)

        mock_ib.placeOrder.assert_called_once()
        order = mock_ib.placeOrder.call_args.args[1]
        assert order.lmtPrice == 155.0
        assert order.orderType == "LMT"

    async def test_place_order_before_start_raises(self, adapter: BrokerAdapter) -> None:
        with pytest.raises(RuntimeError, match="not running"):
            await adapter.place_order("AAPL", "BUY", 100)

    async def test_place_order_handles_ib_exception(
        self, adapter: BrokerAdapter, mock_ib: MagicMock
    ) -> None:
        await adapter.start()
        mock_ib.placeOrder.side_effect = RuntimeError("connection lost")

        order_id = await adapter.place_order("AAPL", "BUY", 100)
        assert order_id is None

    async def test_place_order_handles_none_trade(
        self, adapter: BrokerAdapter, mock_ib: MagicMock
    ) -> None:
        await adapter.start()
        mock_ib.placeOrder.return_value = None

        order_id = await adapter.place_order("AAPL", "BUY", 100)
        assert order_id is None


class TestBrokerAdapterCancelOrder:
    async def test_cancel_order_calls_ib(self, adapter: BrokerAdapter, mock_ib: MagicMock) -> None:
        await adapter.start()
        await adapter.cancel_order("42")
        mock_ib.cancelOrder.assert_called_once_with(42)

    async def test_cancel_order_before_start_raises(self, adapter: BrokerAdapter) -> None:
        with pytest.raises(RuntimeError, match="not running"):
            await adapter.cancel_order("42")

    async def test_cancel_order_handles_ib_exception(
        self, adapter: BrokerAdapter, mock_ib: MagicMock
    ) -> None:
        await adapter.start()
        mock_ib.cancelOrder.side_effect = RuntimeError("invalid order")
        await adapter.cancel_order("42")


class TestBrokerAdapterOrderStatus:
    async def test_order_status_emits_status_changed(
        self, adapter: BrokerAdapter, collected_events: list, event_bus: EventBus
    ) -> None:
        await adapter.start()
        trade = _make_trade(order_id=1, status="Submitted")
        adapter._on_order_status(trade)
        await event_bus.drain()

        changed = [e for e in collected_events if isinstance(e, OrderStatusChangedEvent)]
        assert len(changed) >= 1
        assert changed[0].order_id == "1"
        assert changed[0].status == "Submitted"

    async def test_order_status_cancelled_emits_cancelled(
        self, adapter: BrokerAdapter, collected_events: list, event_bus: EventBus
    ) -> None:
        await adapter.start()
        trade = _make_trade(order_id=1, status="Cancelled")
        adapter._on_order_status(trade)
        await event_bus.drain()

        cancelled = [e for e in collected_events if isinstance(e, OrderCancelledEvent)]
        assert len(cancelled) >= 1
        assert cancelled[0].order_id == "1"

    async def test_order_status_cancelled_removes_trade(self, adapter: BrokerAdapter) -> None:
        await adapter.start()
        trade = _make_trade(order_id=1, status="Submitted")
        adapter._trades[1] = trade
        cancelled_trade = _make_trade(order_id=1, status="Cancelled")
        adapter._on_order_status(cancelled_trade)
        await asyncio.sleep(0.05)
        assert 1 not in adapter._trades

    async def test_order_status_not_running_ignored(
        self, adapter: BrokerAdapter, collected_events: list, event_bus: EventBus
    ) -> None:
        trade = _make_trade(order_id=1, status="Submitted")
        adapter._on_order_status(trade)
        await event_bus.drain()
        changed = [e for e in collected_events if isinstance(e, OrderStatusChangedEvent)]
        assert len(changed) == 0

    async def test_order_status_none_trade_ignored(
        self, adapter: BrokerAdapter, collected_events: list, event_bus: EventBus
    ) -> None:
        await adapter.start()
        adapter._on_order_status(None)
        await event_bus.drain()
        changed = [e for e in collected_events if isinstance(e, OrderStatusChangedEvent)]
        assert len(changed) == 0

    async def test_order_status_stores_trade(self, adapter: BrokerAdapter) -> None:
        await adapter.start()
        trade = _make_trade(order_id=5, status="Filled")
        adapter._on_order_status(trade)
        await asyncio.sleep(0.05)
        assert 5 in adapter._trades


class TestBrokerAdapterFillTracking:
    async def test_exec_details_emits_filled_event(
        self, adapter: BrokerAdapter, collected_events: list, event_bus: EventBus
    ) -> None:
        await adapter.start()
        trade = _make_trade(order_id=1)
        fill = _make_fill(symbol="AAPL", side="BUY", price=150.25, shares=100)
        adapter._on_exec_details(trade, fill)
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].order_id == "1"
        assert filled[0].symbol == "AAPL"
        assert filled[0].side == "BUY"
        assert filled[0].fill_price == 150.25
        assert filled[0].fill_quantity == 100

    async def test_exec_details_not_running_ignored(
        self, adapter: BrokerAdapter, collected_events: list, event_bus: EventBus
    ) -> None:
        trade = _make_trade(order_id=1)
        fill = _make_fill(symbol="AAPL", side="BUY", price=150.25, shares=100)
        adapter._on_exec_details(trade, fill)
        await event_bus.drain()
        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) == 0

    async def test_exec_details_none_trade_ignored(
        self, adapter: BrokerAdapter, collected_events: list, event_bus: EventBus
    ) -> None:
        await adapter.start()
        adapter._on_exec_details(None, None)
        await event_bus.drain()
        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) == 0


class TestBrokerAdapterOrderRequestEvent:
    async def test_order_request_triggers_place_order(
        self, adapter: BrokerAdapter, mock_ib: MagicMock, event_bus: EventBus
    ) -> None:
        await adapter.start()
        trade = _make_trade(order_id=10, symbol="MSFT", side="SELL", quantity=50)
        mock_ib.placeOrder.return_value = trade

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="MSFT",
                side="SELL",
                quantity=50,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        mock_ib.placeOrder.assert_called_once()

    async def test_order_request_emits_submitted(
        self,
        adapter: BrokerAdapter,
        mock_ib: MagicMock,
        collected_events: list,
        event_bus: EventBus,
    ) -> None:
        await adapter.start()
        trade = _make_trade(order_id=10, symbol="MSFT", side="SELL", quantity=50)
        mock_ib.placeOrder.return_value = trade

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="MSFT", side="SELL", quantity=50, order_type="MKT", source="test"
            )
        )
        await event_bus.drain()

        submitted = [e for e in collected_events if isinstance(e, OrderSubmittedEvent)]
        assert len(submitted) >= 1
        assert submitted[0].symbol == "MSFT"
        assert submitted[0].side == "SELL"
        assert submitted[0].quantity == 50
