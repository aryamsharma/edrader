from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BaseEvent,
    BrokerDisconnectedEvent,
    MarketTickEvent,
    OrderFilledEvent,
    OrderRequestedEvent,
    RiskViolationEvent,
    SignalGeneratedEvent,
    SignalRejectedEvent,
    TradingHaltedEvent,
)
from trading_platform.monitoring.logging import get_logger

logger = get_logger(__name__)


class RiskEngine:
    def __init__(
        self,
        event_bus: EventBus,
        max_position_size: int = 100,
        max_daily_loss: float = 1000.0,
        max_leverage: float = 2.0,
        max_symbol_exposure: float = 50_000.0,
        max_concurrent_positions: int = 10,
        stale_market_seconds: float = 300.0,
    ) -> None:
        self._event_bus = event_bus
        self._max_position_size = max_position_size
        self._max_daily_loss = max_daily_loss
        self._max_leverage = max_leverage
        self._max_symbol_exposure = max_symbol_exposure
        self._max_concurrent_positions = max_concurrent_positions
        self._stale_market_seconds = stale_market_seconds
        self._running = False
        self._kill_switch = False
        self._daily_realized_pnl: float = 0.0
        self._last_tick_time: dict[str, datetime] = {}
        self._positions: dict[str, int] = {}
        self._exposure: float = 0.0
        self._equity: float = 100_000.0
        self._signal_unsub: Any = None
        self._fill_unsub: Any = None
        self._tick_unsub: Any = None
        self._disconnect_unsub: Any = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch

    @property
    def daily_realized_pnl(self) -> float:
        return self._daily_realized_pnl

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._signal_unsub = await self._subscribe_signals()
        self._fill_unsub = await self._subscribe_fills()
        self._tick_unsub = await self._subscribe_ticks()
        self._disconnect_unsub = await self._subscribe_disconnects()
        logger.info("risk_engine_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for unsub in (
            self._signal_unsub,
            self._fill_unsub,
            self._tick_unsub,
            self._disconnect_unsub,
        ):
            if unsub is not None:
                unsub()
        self._signal_unsub = None
        self._fill_unsub = None
        self._tick_unsub = None
        self._disconnect_unsub = None
        logger.info("risk_engine_stopped")

    def activate_kill_switch(self) -> None:
        self._kill_switch = True
        logger.warning("kill_switch_activated")

    def deactivate_kill_switch(self) -> None:
        self._kill_switch = False
        logger.info("kill_switch_deactivated")

    def update_portfolio_state(
        self,
        positions: dict[str, int] | None = None,
        exposure: float | None = None,
        equity: float | None = None,
        daily_realized_pnl: float | None = None,
    ) -> None:
        if positions is not None:
            self._positions = positions
        if exposure is not None:
            self._exposure = exposure
        if equity is not None:
            self._equity = equity
        if daily_realized_pnl is not None:
            self._daily_realized_pnl = daily_realized_pnl

    def reset_daily_pnl(self) -> None:
        self._daily_realized_pnl = 0.0
        logger.info("daily_pnl_reset")

    async def _on_signal(self, event: BaseEvent) -> None:
        assert isinstance(event, SignalGeneratedEvent)
        if not self._running:
            return

        if self._kill_switch:
            await self._reject(event, "kill_switch_active")
            return

        checks = [
            ("max_position_size", self._check_max_position_size(event)),
            ("max_daily_loss", self._check_daily_loss(event)),
            ("max_leverage", self._check_leverage(event)),
            ("max_symbol_exposure", self._check_symbol_exposure(event)),
            ("max_concurrent_positions", self._check_concurrent_positions(event)),
            ("stale_market", self._check_stale_market(event)),
        ]

        for rule_name, result in checks:
            if result is not None:
                await self._reject(event, result)
                await self._event_bus.publish(
                    RiskViolationEvent(
                        strategy_id=event.strategy_id,
                        rule=rule_name,
                        reason=result,
                        source="risk_engine",
                    )
                )
                return

        await self._approve(event)

    async def _on_fill(self, event: BaseEvent) -> None:
        assert isinstance(event, OrderFilledEvent)
        if not self._running:
            return

        pos = self._positions
        sym = event.symbol
        if event.side == "BUY":
            pos[sym] = pos.get(sym, 0) + event.fill_quantity
        elif event.side == "SELL":
            pos[sym] = pos.get(sym, 0) - event.fill_quantity

    async def _on_tick(self, event: BaseEvent) -> None:
        assert isinstance(event, MarketTickEvent)
        if not self._running:
            return
        self._last_tick_time[event.symbol] = event.timestamp

    async def _on_disconnect(self, event: BaseEvent) -> None:
        assert isinstance(event, BrokerDisconnectedEvent)
        if not self._running:
            return
        self._kill_switch = True
        await self._event_bus.publish(
            TradingHaltedEvent(reason="broker_disconnected", source="risk_engine")
        )
        logger.warning("trading_halted_due_to_disconnect")

    def _check_max_position_size(self, event: SignalGeneratedEvent) -> str | None:
        if event.suggested_size > self._max_position_size:
            return f"suggested_size {event.suggested_size} exceeds max {self._max_position_size}"
        return None

    def _check_daily_loss(self, event: SignalGeneratedEvent) -> str | None:
        current_pos = self._positions.get(event.symbol, 0)
        is_reducing = (current_pos > 0 and event.side == "SELL") or (
            current_pos < 0 and event.side == "BUY"
        )

        if is_reducing:
            return None

        if abs(self._daily_realized_pnl) >= self._max_daily_loss:
            return f"daily_loss_limit_reached: {self._daily_realized_pnl}"
        return None

    def _check_leverage(self, event: SignalGeneratedEvent) -> str | None:  # noqa: ARG002
        if self._equity <= 0:
            return "no_equity"
        current_leverage = self._exposure / self._equity
        if current_leverage >= self._max_leverage:
            return f"leverage {current_leverage:.2f} exceeds max {self._max_leverage}"
        return None

    def _check_symbol_exposure(self, event: SignalGeneratedEvent) -> str | None:  # noqa: ARG002
        return None

    def _check_concurrent_positions(self, event: SignalGeneratedEvent) -> str | None:
        non_zero = sum(1 for qty in self._positions.values() if qty != 0)
        if event.symbol in self._positions and self._positions[event.symbol] != 0:
            return None
        if non_zero >= self._max_concurrent_positions:
            return f"concurrent_positions {non_zero} exceeds max {self._max_concurrent_positions}"
        return None

    def _check_stale_market(self, event: SignalGeneratedEvent) -> str | None:
        if event.symbol not in self._last_tick_time:
            return None
        now = datetime.now(UTC)
        elapsed = (now - self._last_tick_time[event.symbol]).total_seconds()
        if elapsed > self._stale_market_seconds:
            return f"stale_market: {elapsed:.0f}s since last tick"
        return None

    async def _approve(self, event: SignalGeneratedEvent) -> None:
        await self._event_bus.publish(
            OrderRequestedEvent(
                symbol=event.symbol,
                side=event.side,
                quantity=event.suggested_size,
                order_type="MKT",
                source="risk_engine",
            )
        )
        logger.info(
            "signal_approved",
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.suggested_size,
        )

    async def _reject(self, event: SignalGeneratedEvent, reason: str) -> None:
        await self._event_bus.publish(
            SignalRejectedEvent(
                strategy_id=event.strategy_id,
                symbol=event.symbol,
                reason=reason,
                source="risk_engine",
            )
        )
        logger.info(
            "signal_rejected",
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            reason=reason,
        )

    async def _subscribe_signals(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_signal(event)

        self._event_bus.subscribe(SignalGeneratedEvent, handler, name="risk_engine_signal")
        return lambda: self._event_bus.unsubscribe(SignalGeneratedEvent, handler)

    async def _subscribe_fills(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_fill(event)

        self._event_bus.subscribe(OrderFilledEvent, handler, name="risk_engine_fill")
        return lambda: self._event_bus.unsubscribe(OrderFilledEvent, handler)

    async def _subscribe_ticks(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_tick(event)

        self._event_bus.subscribe(MarketTickEvent, handler, name="risk_engine_tick")
        return lambda: self._event_bus.unsubscribe(MarketTickEvent, handler)

    async def _subscribe_disconnects(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_disconnect(event)

        self._event_bus.subscribe(BrokerDisconnectedEvent, handler, name="risk_engine_disconnect")
        return lambda: self._event_bus.unsubscribe(BrokerDisconnectedEvent, handler)
