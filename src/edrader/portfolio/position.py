from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BaseEvent,
    ExposureLimitEvent,
    ExposureUpdatedEvent,
    MarketTickEvent,
    OrderFilledEvent,
    PnLUpdatedEvent,
    PositionClosedEvent,
    PositionOpenedEvent,
    PositionUpdate,
)
from edrader.monitoring.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Position:
    symbol: str = ""
    quantity: int = 0
    avg_cost: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class ExposureSnapshot:
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    long_count: int = 0
    short_count: int = 0


class PositionManager:
    def __init__(
        self,
        event_bus: EventBus,
        db_manager: Any | None = None,
        initial_capital: float = 100_000.0,
        max_symbol_exposure: float | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._db_manager = db_manager
        self._initial_capital = initial_capital
        self._max_symbol_exposure = max_symbol_exposure
        self._positions: dict[str, Position] = {}
        self._market_prices: dict[str, float] = {}
        self._running = False
        self._fill_unsub: Any = None
        self._tick_unsub: Any = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    @property
    def total_realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self._positions.values())

    @property
    def total_unrealized_pnl(self) -> float:
        total = 0.0
        for sym, pos in self._positions.items():
            total += self._unrealized_pnl(sym, pos)
        return total

    @property
    def total_pnl(self) -> float:
        return self.total_realized_pnl + self.total_unrealized_pnl

    @property
    def equity(self) -> float:
        return self._initial_capital + self.total_pnl

    def exposure(self) -> ExposureSnapshot:
        gross = 0.0
        net = 0.0
        long_count = 0
        short_count = 0
        for sym, pos in self._positions.items():
            price = self._market_prices.get(sym, pos.avg_cost)
            value = price * abs(pos.quantity)
            if pos.quantity > 0:
                gross += value
                net += value
                long_count += 1
            elif pos.quantity < 0:
                gross += value
                net -= value
                short_count += 1
        return ExposureSnapshot(
            gross_exposure=gross,
            net_exposure=net,
            long_count=long_count,
            short_count=short_count,
        )

    @property
    def leverage(self) -> float:
        eq = self.equity
        if eq <= 0:
            return 0.0
        return self.exposure().gross_exposure / eq

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._fill_unsub = await self._subscribe_to_fills()
        self._tick_unsub = await self._subscribe_to_ticks()
        logger.info("position_manager_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._fill_unsub is not None:
            self._fill_unsub()
            self._fill_unsub = None
        if self._tick_unsub is not None:
            self._tick_unsub()
            self._tick_unsub = None
        logger.info("position_manager_stopped")

    async def process_fill(self, event: OrderFilledEvent) -> None:
        if not self._running:
            return

        old_pos = self._positions.get(event.symbol)
        old_qty = old_pos.quantity if old_pos else 0

        self._update_position(event.symbol, event.side, event.fill_quantity, event.fill_price)

        pos = self._positions[event.symbol]

        if old_qty == 0 and pos.quantity != 0:
            await self._event_bus.publish(
                PositionOpenedEvent(
                    symbol=event.symbol,
                    quantity=pos.quantity,
                    avg_cost=pos.avg_cost,
                    source="position_manager",
                )
            )
        elif old_qty != 0 and pos.quantity == 0:
            await self._event_bus.publish(
                PositionClosedEvent(
                    symbol=event.symbol,
                    realized_pnl=pos.realized_pnl,
                    source="position_manager",
                )
            )

        await self._event_bus.publish(
            PnLUpdatedEvent(
                symbol=event.symbol,
                unrealized_pnl=self._unrealized_pnl(event.symbol, pos),
                realized_pnl=pos.realized_pnl,
                source="position_manager",
            )
        )
        self._persist_position(event.symbol)

        logger.info(
            "position_updated",
            symbol=event.symbol,
            quantity=pos.quantity,
            avg_cost=pos.avg_cost,
            realized_pnl=pos.realized_pnl,
        )

        await self._publish_exposure()

    async def _publish_exposure(self) -> None:
        snap = self.exposure()
        lev = self.leverage
        eq = self.equity
        await self._event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=snap.gross_exposure,
                net_exposure=snap.net_exposure,
                leverage=lev,
                long_count=snap.long_count,
                short_count=snap.short_count,
                equity=eq,
                source="position_manager",
            )
        )

        if self._max_symbol_exposure is not None and self._max_symbol_exposure > 0:
            for sym, pos in self._positions.items():
                price = self._market_prices.get(sym, pos.avg_cost)
                value = price * abs(pos.quantity)
                if value > self._max_symbol_exposure:
                    await self._event_bus.publish(
                        ExposureLimitEvent(
                            current_exposure=value,
                            limit=self._max_symbol_exposure,
                            source="position_manager",
                        )
                    )

    def _update_position(self, symbol: str, side: str, fill_qty: int, fill_price: float) -> None:
        if symbol not in self._positions:
            self._positions[symbol] = Position(symbol=symbol)

        pos = self._positions[symbol]
        prev_qty = pos.quantity

        if side == "BUY":
            if prev_qty >= 0:
                new_qty = prev_qty + fill_qty
                pos.avg_cost = (
                    ((pos.avg_cost * prev_qty) + (fill_price * fill_qty)) / new_qty
                    if new_qty > 0
                    else 0.0
                )
                pos.quantity = new_qty
            else:
                covering = min(fill_qty, abs(prev_qty))
                pos.realized_pnl += (pos.avg_cost - fill_price) * covering
                remaining_buy = fill_qty - covering
                pos.quantity = prev_qty + covering
                if remaining_buy > 0:
                    pos.quantity = remaining_buy
                    pos.avg_cost = fill_price
                elif pos.quantity == 0:
                    pos.avg_cost = 0.0

        elif side == "SELL":
            if prev_qty <= 0:
                new_qty = prev_qty - fill_qty
                pos.avg_cost = (
                    ((pos.avg_cost * abs(prev_qty)) + (fill_price * fill_qty)) / abs(new_qty)
                    if new_qty < 0
                    else 0.0
                )
                pos.quantity = new_qty
            else:
                covering = min(fill_qty, prev_qty)
                pos.realized_pnl += (fill_price - pos.avg_cost) * covering
                remaining_sell = fill_qty - covering
                pos.quantity = prev_qty - covering
                if remaining_sell > 0:
                    pos.quantity = -remaining_sell
                    pos.avg_cost = fill_price
                elif pos.quantity == 0:
                    pos.avg_cost = 0.0

    def _unrealized_pnl(self, symbol: str, pos: Position) -> float:
        price = self._market_prices.get(symbol, pos.avg_cost)
        if pos.quantity > 0:
            return (price - pos.avg_cost) * pos.quantity
        if pos.quantity < 0:
            return (pos.avg_cost - price) * abs(pos.quantity)
        return 0.0

    async def _on_fill(self, event: BaseEvent) -> None:
        assert isinstance(event, OrderFilledEvent)
        await self.process_fill(event)

    async def _on_tick(self, event: BaseEvent) -> None:
        assert isinstance(event, MarketTickEvent)
        if not self._running:
            return
        price = event.price
        if price == 0.0 and event.bid != 0.0 and event.ask != 0.0:
            price = (event.bid + event.ask) / 2
        if price == 0.0:
            return
        self._market_prices[event.symbol] = price

        if event.symbol in self._positions:
            pos = self._positions[event.symbol]
            upnl = self._unrealized_pnl(event.symbol, pos)
            await self._event_bus.publish(
                PnLUpdatedEvent(
                    symbol=event.symbol,
                    unrealized_pnl=upnl,
                    realized_pnl=pos.realized_pnl,
                    source="position_manager",
                )
            )
            await self._event_bus.publish(
                PositionUpdate(
                    symbol=event.symbol,
                    position=pos.quantity,
                    avg_cost=pos.avg_cost,
                    market_price=price,
                    source="position_manager",
                )
            )
            await self._publish_exposure()

    def _persist_position(self, symbol: str) -> None:
        if self._db_manager is None:
            return
        pos = self._positions.get(symbol)
        if pos is None:
            return
        try:
            from datetime import UTC, datetime

            from edrader.persistence.models import PositionRecord

            with self._db_manager.session() as session:
                record = session.query(PositionRecord).filter_by(symbol=symbol).first()
                if record is None:
                    record = PositionRecord(
                        symbol=symbol,
                        quantity=pos.quantity,
                        avg_cost=pos.avg_cost,
                        updated_at=datetime.now(UTC),
                    )
                    session.add(record)
                else:
                    record.quantity = pos.quantity
                    record.avg_cost = pos.avg_cost
                    record.updated_at = datetime.now(UTC)
        except Exception as e:
            logger.error("position_persist_failed", symbol=symbol, error=str(e))

    async def _subscribe_to_fills(self) -> Any:
        async def on_fill(event: BaseEvent) -> None:
            await self._on_fill(event)

        self._event_bus.subscribe(OrderFilledEvent, on_fill, name="position_manager_fill")
        return lambda: self._event_bus.unsubscribe(OrderFilledEvent, on_fill)

    async def _subscribe_to_ticks(self) -> Any:
        async def on_tick(event: BaseEvent) -> None:
            await self._on_tick(event)

        self._event_bus.subscribe(MarketTickEvent, on_tick, name="position_manager_tick")
        return lambda: self._event_bus.unsubscribe(MarketTickEvent, on_tick)
