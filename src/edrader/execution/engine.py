from __future__ import annotations

import asyncio
import time
from typing import Any

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BaseEvent,
    ExposureUpdatedEvent,
    MarketTickEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    OrderRequestedEvent,
    OrderSubmittedEvent,
    SignalApprovedEvent,
)
from edrader.execution.sizing import SizingEngine
from edrader.monitoring.logging import get_logger

logger = get_logger(__name__)


class ExecutionEngine:
    def __init__(
        self,
        event_bus: EventBus,
        sizing_engine: SizingEngine | None = None,
        default_order_type: str = "MKT",
        max_retries: int = 3,
        throttle_delay: float = 0.5,
    ) -> None:
        self._event_bus = event_bus
        self._sizing_engine = sizing_engine or SizingEngine()
        self._default_order_type = default_order_type
        self._max_retries = max_retries
        self._throttle_delay = throttle_delay
        self._running = False
        self._last_order_time: dict[str, float] = {}
        self._active_orders: dict[str, dict[str, Any]] = {}
        self._pending_retries: dict[str, int] = {}
        self._retry_tasks: set[asyncio.Task[None]] = set()
        self._prices: dict[str, float] = {}
        self._equity: float = 100_000.0
        self._approved_unsub: Any = None
        self._tick_unsub: Any = None
        self._submitted_unsub: Any = None
        self._filled_unsub: Any = None
        self._cancelled_unsub: Any = None
        self._exposure_unsub: Any = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_order_count(self) -> int:
        return len(self._active_orders)

    @property
    def active_orders(self) -> dict[str, dict[str, Any]]:
        return dict(self._active_orders)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._approved_unsub = await self._subscribe_approved()
        self._tick_unsub = await self._subscribe_ticks()
        self._submitted_unsub = await self._subscribe_submitted()
        self._filled_unsub = await self._subscribe_filled()
        self._cancelled_unsub = await self._subscribe_cancelled()
        self._exposure_unsub = await self._subscribe_exposure()
        logger.info("execution_engine_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for unsub in (
            self._approved_unsub,
            self._tick_unsub,
            self._submitted_unsub,
            self._filled_unsub,
            self._cancelled_unsub,
            self._exposure_unsub,
        ):
            if unsub is not None:
                unsub()
        self._approved_unsub = None
        self._tick_unsub = None
        self._submitted_unsub = None
        self._filled_unsub = None
        self._cancelled_unsub = None
        self._exposure_unsub = None
        if self._retry_tasks:
            for task in self._retry_tasks:
                task.cancel()
            await asyncio.gather(*self._retry_tasks, return_exceptions=True)
            self._retry_tasks.clear()
        self._last_order_time.clear()
        self._active_orders.clear()
        self._pending_retries.clear()
        self._prices.clear()
        logger.info("execution_engine_stopped")

    async def _on_approved_signal(self, event: BaseEvent) -> None:
        assert isinstance(event, SignalApprovedEvent)
        if not self._running:
            return

        if self._throttle_delay > 0:
            delay = self._throttle_remaining(event.symbol)
            if delay > 0:
                logger.info(
                    "execution_throttled",
                    symbol=event.symbol,
                    delay_seconds=round(delay, 2),
                )
                await self._event_bus.publish(
                    OrderSubmittedEvent(
                        order_id="",
                        symbol=event.symbol,
                        side=event.side,
                        quantity=0,
                        order_type="",
                        source="execution_engine",
                    )
                )
                return

        price = self._prices.get(event.symbol)

        final_size = self._sizing_engine.compute_size(
            suggested_size=event.suggested_size,
            price=price,
            equity=self._equity,
            symbol=event.symbol,
        )

        if final_size <= 0:
            logger.info("execution_skipped_zero_size", symbol=event.symbol)
            return

        await self._event_bus.publish(
            OrderRequestedEvent(
                symbol=event.symbol,
                side=event.side,
                quantity=final_size,
                order_type=self._default_order_type,
                source="execution_engine",
            )
        )

        self._last_order_time[event.symbol] = time.monotonic()

        if self._max_retries > 0 and final_size > 0:
            key = f"{event.symbol}:{event.side}"
            self._pending_retries[key] = self._max_retries
            task = asyncio.create_task(
                self._retry_pending_order(
                    event.symbol, event.side, final_size, self._default_order_type
                )
            )
            self._retry_tasks.add(task)
            task.add_done_callback(self._retry_tasks.discard)

        logger.info(
            "order_requested",
            symbol=event.symbol,
            side=event.side,
            quantity=final_size,
            order_type=self._default_order_type,
        )

    async def _retry_pending_order(
        self, symbol: str, side: str, size: int, order_type: str
    ) -> None:
        try:
            await asyncio.sleep(2.0)
            if not self._running:
                return
            key = f"{symbol}:{side}"
            remaining = self._pending_retries.get(key, 0)
            if remaining <= 0:
                return
            self._pending_retries[key] = remaining - 1
            logger.info(
                "order_retry",
                symbol=symbol,
                side=side,
                remaining=remaining - 1,
            )
            await self._event_bus.publish(
                OrderRequestedEvent(
                    symbol=symbol,
                    side=side,
                    quantity=size,
                    order_type=order_type,
                    source="execution_engine",
                )
            )
        except Exception:
            logger.exception("order_retry_failed")

    async def _on_tick(self, event: BaseEvent) -> None:
        assert isinstance(event, MarketTickEvent)
        if not self._running:
            return
        self._prices[event.symbol] = event.price

    async def _on_submitted(self, event: BaseEvent) -> None:
        assert isinstance(event, OrderSubmittedEvent)
        if not self._running:
            return
        if not event.order_id:
            return
        self._active_orders[event.order_id] = {
            "symbol": event.symbol,
            "side": event.side,
            "quantity": event.quantity,
            "order_type": event.order_type,
        }
        key = f"{event.symbol}:{event.side}"
        self._pending_retries.pop(key, None)

    async def _on_exposure_update(self, event: BaseEvent) -> None:
        assert isinstance(event, ExposureUpdatedEvent)
        if not self._running:
            return
        self._equity = event.equity

    async def _on_filled(self, event: BaseEvent) -> None:
        assert isinstance(event, OrderFilledEvent)
        if not self._running:
            return
        self._active_orders.pop(event.order_id, None)

    async def _on_cancelled(self, event: BaseEvent) -> None:
        assert isinstance(event, OrderCancelledEvent)
        if not self._running:
            return
        self._active_orders.pop(event.order_id, None)

    def _throttle_remaining(self, symbol: str) -> float:
        last = self._last_order_time.get(symbol)
        if last is None:
            return 0.0
        elapsed = time.monotonic() - last
        remaining = self._throttle_delay - elapsed
        return max(0.0, remaining)

    async def _subscribe_approved(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_approved_signal(event)

        self._event_bus.subscribe(SignalApprovedEvent, handler, name="execution_engine_approved")
        return lambda: self._event_bus.unsubscribe(SignalApprovedEvent, handler)

    async def _subscribe_ticks(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_tick(event)

        self._event_bus.subscribe(MarketTickEvent, handler, name="execution_engine_tick")
        return lambda: self._event_bus.unsubscribe(MarketTickEvent, handler)

    async def _subscribe_submitted(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_submitted(event)

        self._event_bus.subscribe(OrderSubmittedEvent, handler, name="execution_engine_submitted")
        return lambda: self._event_bus.unsubscribe(OrderSubmittedEvent, handler)

    async def _subscribe_filled(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_filled(event)

        self._event_bus.subscribe(OrderFilledEvent, handler, name="execution_engine_filled")
        return lambda: self._event_bus.unsubscribe(OrderFilledEvent, handler)

    async def _subscribe_exposure(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_exposure_update(event)

        self._event_bus.subscribe(ExposureUpdatedEvent, handler, name="execution_engine_exposure")
        return lambda: self._event_bus.unsubscribe(ExposureUpdatedEvent, handler)

    async def _subscribe_cancelled(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_cancelled(event)

        self._event_bus.subscribe(OrderCancelledEvent, handler, name="execution_engine_cancelled")
        return lambda: self._event_bus.unsubscribe(OrderCancelledEvent, handler)
