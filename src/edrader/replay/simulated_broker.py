from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BarCloseEvent,
    BaseEvent,
    MarketTickEvent,
    OrderFilledEvent,
    OrderRequestedEvent,
    OrderStatusChangedEvent,
    OrderSubmittedEvent,
)
from edrader.monitoring.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PendingOrder:
    symbol: str
    side: str
    quantity: int
    order_type: str
    limit_price: float | None
    order_id: str


@dataclass
class CompletedOrder:
    order_id: str
    symbol: str
    side: str
    quantity: int
    fill_price: float
    commission: float = 0.0


class SimulatedBroker:
    def __init__(
        self,
        event_bus: EventBus,
        slippage_bps: float = 0.0,
        commission_per_trade: float = 0.0,
    ) -> None:
        self._event_bus = event_bus
        self._slippage_bps = slippage_bps
        self._commission_per_trade = commission_per_trade
        self._running = False
        self._prices: dict[str, float] = {}
        self._pending_orders: dict[str, PendingOrder] = {}
        self._completed_orders: dict[str, CompletedOrder] = {}
        self._order_counter: int = 0
        self._held_market_orders: list[PendingOrder] = []
        self._order_req_unsub: Any = None
        self._bar_close_unsub: Any = None
        self._tick_unsub: Any = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_order_ids(self) -> list[str]:
        return list(self._pending_orders.keys()) + [o.order_id for o in self._held_market_orders]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._order_req_unsub = await self._subscribe_order_requests()
        self._bar_close_unsub = await self._subscribe_bar_close()
        self._tick_unsub = await self._subscribe_ticks()
        logger.info("simulated_broker_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for unsub in (self._order_req_unsub, self._bar_close_unsub, self._tick_unsub):
            if unsub is not None:
                unsub()
        self._order_req_unsub = None
        self._bar_close_unsub = None
        self._tick_unsub = None
        self._prices.clear()
        self._pending_orders.clear()
        self._completed_orders.clear()
        self._held_market_orders.clear()
        logger.info("simulated_broker_stopped")

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"SIM-{uuid.uuid4().hex[:8]}-{self._order_counter}"

    def _apply_slippage(self, price: float, side: str) -> float:
        if self._slippage_bps == 0.0:
            return price
        factor = self._slippage_bps / 10_000.0
        if side == "BUY":
            return round(price * (1 + factor), 2)
        return round(price * (1 - factor), 2)

    async def _fill_order(self, order: PendingOrder, price: float) -> None:
        filled_price = self._apply_slippage(price, order.side)
        order_id = order.order_id

        await self._event_bus.publish(
            OrderSubmittedEvent(
                order_id=order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                order_type=order.order_type,
                limit_price=order.limit_price,
                source="simulated_broker",
            )
        )

        await self._event_bus.publish(
            OrderStatusChangedEvent(
                order_id=order_id,
                status="Filled",
                source="simulated_broker",
            )
        )

        await self._event_bus.publish(
            OrderFilledEvent(
                order_id=order_id,
                symbol=order.symbol,
                side=order.side,
                fill_price=filled_price,
                fill_quantity=order.quantity,
                source="simulated_broker",
            )
        )

        commission = self._commission_per_trade
        self._completed_orders[order_id] = CompletedOrder(
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=filled_price,
            commission=commission,
        )

        logger.info(
            "order_filled",
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=filled_price,
            commission=commission,
        )

    async def _on_order_request(self, event: BaseEvent) -> None:
        assert isinstance(event, OrderRequestedEvent)
        if not self._running:
            return

        order_id = self._next_order_id()
        order = PendingOrder(
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            order_type=event.order_type,
            limit_price=event.limit_price,
            order_id=order_id,
        )

        price = self._prices.get(event.symbol)

        if event.order_type == "MKT":
            if price is not None:
                await self._fill_order(order, price)
            else:
                self._held_market_orders.append(order)
                logger.info(
                    "order_held_no_price",
                    symbol=event.symbol,
                    order_id=order_id,
                )

        elif event.order_type == "LMT" and event.limit_price is not None:
            if price is not None and self._limit_crossed(event.side, price, event.limit_price):
                await self._fill_order(order, price)
            else:
                self._pending_orders[order_id] = order
                logger.info(
                    "limit_order_pending",
                    symbol=event.symbol,
                    order_id=order_id,
                    limit_price=event.limit_price,
                )

    def _limit_crossed(self, side: str, market_price: float, limit_price: float) -> bool:
        if side == "BUY":
            return market_price <= limit_price
        return market_price >= limit_price

    async def _on_bar_close(self, event: BaseEvent) -> None:
        assert isinstance(event, BarCloseEvent)
        if not self._running:
            return
        self._prices[event.symbol] = event.close
        await self._try_fill_held_orders(event.symbol, event.close)

    async def _on_tick(self, event: BaseEvent) -> None:
        assert isinstance(event, MarketTickEvent)
        if not self._running:
            return
        price = event.price
        if price == 0.0:
            return
        self._prices[event.symbol] = price
        await self._try_fill_held_orders(event.symbol, price)

    async def _try_fill_held_orders(self, symbol: str, price: float) -> None:
        held_to_remove: list[PendingOrder] = []
        for order in self._held_market_orders:
            if order.symbol == symbol:
                await self._fill_order(order, price)
                held_to_remove.append(order)
        for order in held_to_remove:
            self._held_market_orders.remove(order)

        pending_to_remove: list[str] = []
        for oid, order in self._pending_orders.items():
            if (
                order.symbol == symbol
                and order.limit_price is not None
                and self._limit_crossed(order.side, price, order.limit_price)
            ):
                await self._fill_order(order, order.limit_price)
                pending_to_remove.append(oid)
        for oid in pending_to_remove:
            self._pending_orders.pop(oid, None)

    async def _subscribe_order_requests(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_order_request(event)

        self._event_bus.subscribe(OrderRequestedEvent, handler, name="simulated_broker_order_req")
        return lambda: self._event_bus.unsubscribe(OrderRequestedEvent, handler)

    async def _subscribe_bar_close(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_bar_close(event)

        self._event_bus.subscribe(BarCloseEvent, handler, name="simulated_broker_bar_close")
        return lambda: self._event_bus.unsubscribe(BarCloseEvent, handler)

    async def _subscribe_ticks(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_tick(event)

        self._event_bus.subscribe(MarketTickEvent, handler, name="simulated_broker_tick")
        return lambda: self._event_bus.unsubscribe(MarketTickEvent, handler)
