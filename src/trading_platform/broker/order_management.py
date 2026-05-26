from __future__ import annotations

import asyncio
from typing import Any

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BaseEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    OrderRequestedEvent,
    OrderStatusChangedEvent,
    OrderSubmittedEvent,
)
from trading_platform.monitoring.logging import get_logger

logger = get_logger(__name__)


class BrokerAdapter:
    def __init__(
        self,
        ib: Any,
        event_bus: EventBus,
    ) -> None:
        self._ib = ib
        self._event_bus = event_bus
        self._running = False
        self._trades: dict[int, Any] = {}
        self._order_status_handler: Any = None
        self._exec_details_handler: Any = None
        self._order_req_unsub: Any = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_order_ids(self) -> list[str]:
        return [str(oid) for oid in self._trades]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._order_status_handler = self._ib.orderStatusEvent.connect(self._on_order_status)
        self._exec_details_handler = self._ib.execDetailsEvent.connect(self._on_exec_details)
        self._order_req_unsub = await self._subscribe_to_order_requests()
        logger.info("broker_adapter_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._order_status_handler is not None:
            self._ib.orderStatusEvent.disconnect(self._order_status_handler)
            self._order_status_handler = None
        if self._exec_details_handler is not None:
            self._ib.execDetailsEvent.disconnect(self._exec_details_handler)
            self._exec_details_handler = None
        if self._order_req_unsub is not None:
            self._order_req_unsub()
            self._order_req_unsub = None
        self._trades.clear()
        logger.info("broker_adapter_stopped")

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MKT",
        limit_price: float | None = None,
        exchange: str = "SMART",
        currency: str = "USD",
        sec_type: str = "STK",
    ) -> str | None:
        if not self._running:
            raise RuntimeError("BrokerAdapter is not running")

        contract = self._make_contract(symbol, exchange, currency, sec_type)
        order = self._make_order(side, quantity, order_type, limit_price)

        try:
            trade = self._ib.placeOrder(contract, order)
        except Exception as e:
            logger.error(
                "order_placement_failed",
                symbol=symbol,
                side=side,
                error=str(e),
            )
            return None

        if trade is None or trade.order is None or trade.order.orderId is None:
            logger.error(
                "order_submission_incomplete",
                symbol=symbol,
                side=side,
            )
            return None

        order_id = str(trade.order.orderId)
        self._trades[trade.order.orderId] = trade

        await self._event_bus.publish(
            OrderSubmittedEvent(
                order_id=order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                source="broker_adapter",
            )
        )

        logger.info(
            "order_submitted",
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
        )
        return order_id

    async def cancel_order(self, order_id: str) -> None:
        if not self._running:
            raise RuntimeError("BrokerAdapter is not running")
        try:
            self._ib.cancelOrder(int(order_id))
        except Exception as e:
            logger.error(
                "order_cancellation_failed",
                order_id=order_id,
                error=str(e),
            )
            return
        logger.info("order_cancellation_requested", order_id=order_id)

    def _make_contract(self, symbol: str, exchange: str, currency: str, sec_type: str) -> Any:
        if sec_type == "STK":
            from ib_insync import Stock

            return Stock(symbol, exchange, currency)
        from ib_insync import Contract

        return Contract(symbol, sec_type, exchange, currency=currency)  # type: ignore[arg-type]

    def _make_order(
        self, side: str, quantity: int, order_type: str, limit_price: float | None = None
    ) -> Any:
        if order_type == "MKT":
            from ib_insync import MarketOrder

            return MarketOrder(side, quantity)
        if order_type == "LMT" and limit_price is not None:
            from ib_insync import LimitOrder

            return LimitOrder(side, quantity, limit_price)
        if order_type == "STP" and limit_price is not None:
            from ib_insync import StopOrder

            return StopOrder(side, quantity, limit_price)
        from ib_insync import MarketOrder

        return MarketOrder(side, quantity)

    def _on_order_status(self, trade: Any) -> None:
        if not self._running:
            return
        if trade is None or trade.order is None:
            return
        asyncio.create_task(self._handle_order_status(trade))

    async def _handle_order_status(self, trade: Any) -> None:
        order_id = str(trade.order.orderId)
        status = str(trade.orderStatus.status) if trade.orderStatus else "Unknown"

        self._trades[trade.order.orderId] = trade

        await self._event_bus.publish(
            OrderStatusChangedEvent(order_id=order_id, status=status, source="broker_adapter")
        )

        if status == "Cancelled":
            await self._event_bus.publish(
                OrderCancelledEvent(order_id=order_id, reason="cancelled", source="broker_adapter")
            )
            self._trades.pop(trade.order.orderId, None)
            logger.info("order_cancelled", order_id=order_id)

        logger.debug("order_status_update", order_id=order_id, status=status)

    def _on_exec_details(self, trade: Any, fill: Any) -> None:
        if not self._running:
            return
        if trade is None or fill is None:
            return
        asyncio.create_task(self._handle_exec_details(trade, fill))

    async def _handle_exec_details(self, trade: Any, fill: Any) -> None:
        order_id = str(trade.order.orderId)
        execution = fill.execution
        symbol = str(execution.symbol) if execution else ""
        side = str(execution.side) if execution else ""
        fill_price = float(execution.price) if execution else 0.0
        fill_quantity = int(execution.shares) if execution else 0

        await self._event_bus.publish(
            OrderFilledEvent(
                order_id=order_id,
                symbol=symbol,
                side=side,
                fill_price=fill_price,
                fill_quantity=fill_quantity,
                source="broker_adapter",
            )
        )
        logger.info(
            "order_filled",
            order_id=order_id,
            symbol=symbol,
            fill_price=fill_price,
            fill_quantity=fill_quantity,
        )

    async def _subscribe_to_order_requests(self) -> Any:
        async def on_request(event: BaseEvent) -> None:
            req = event
            assert isinstance(req, OrderRequestedEvent)
            await self.place_order(
                symbol=req.symbol,
                side=req.side,
                quantity=req.quantity,
                order_type=req.order_type,
                limit_price=req.limit_price,
            )

        self._event_bus.subscribe(OrderRequestedEvent, on_request, name="adapter_order_request")
        return lambda: self._event_bus.unsubscribe(OrderRequestedEvent, on_request)
