from __future__ import annotations

import pytest

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    MarketTickEvent,
    OrderFilledEvent,
    PnLUpdatedEvent,
    PositionClosedEvent,
    PositionOpenedEvent,
    PositionUpdate,
)
from trading_platform.portfolio.position import PositionManager


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
async def manager(event_bus: EventBus) -> PositionManager:
    m = PositionManager(event_bus=event_bus, initial_capital=100_000.0)
    await m.start()
    yield m
    await m.stop()


class TestPositionManagerLifecycle:
    async def test_initial_state(self, manager: PositionManager) -> None:
        assert manager.is_running is True
        assert manager.positions == {}
        assert manager.total_realized_pnl == 0.0
        assert manager.total_unrealized_pnl == 0.0
        assert manager.total_pnl == 0.0
        assert manager.equity == 100_000.0
        assert manager.leverage == 0.0

    async def test_start_sets_running(self, event_bus: EventBus) -> None:
        m = PositionManager(event_bus=event_bus)
        assert m.is_running is False
        await m.start()
        assert m.is_running is True
        await m.stop()

    async def test_stop_clears_running(self, manager: PositionManager) -> None:
        await manager.stop()
        assert manager.is_running is False

    async def test_start_idempotent(self, manager: PositionManager) -> None:
        await manager.start()
        assert manager.is_running is True

    async def test_stop_idempotent(self, manager: PositionManager) -> None:
        await manager.stop()
        await manager.stop()
        assert manager.is_running is False

    async def test_start_subscribes_to_fills(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        count = event_bus.subscriber_count_for(OrderFilledEvent)
        assert count >= 1
        assert manager.is_running is True
        assert count >= 1

    async def test_start_subscribes_to_ticks(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        count = event_bus.subscriber_count_for(MarketTickEvent)
        assert count >= 1
        assert manager.is_running is True
        assert count >= 1


class TestPositionManagerFillProcessing:
    async def test_buy_opens_long_position(
        self, manager: PositionManager, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.drain()

        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 100
        assert pos.avg_cost == 150.0
        assert pos.realized_pnl == 0.0

        opened = [e for e in collected_events if isinstance(e, PositionOpenedEvent)]
        assert len(opened) >= 1
        assert opened[0].symbol == "AAPL"
        assert opened[0].quantity == 100
        assert opened[0].avg_cost == 150.0

    async def test_buy_adds_to_existing_long(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="BUY",
                fill_price=160.0,
                fill_quantity=50,
                source="test",
            )
        )
        await event_bus.drain()

        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 150
        expected_avg = ((150.0 * 100) + (160.0 * 50)) / 150
        assert pos.avg_cost == pytest.approx(expected_avg)
        assert pos.realized_pnl == 0.0

    async def test_sell_reduces_long_position(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="SELL",
                fill_price=160.0,
                fill_quantity=40,
                source="test",
            )
        )
        await event_bus.drain()

        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 60
        assert pos.avg_cost == 150.0
        assert pos.realized_pnl == pytest.approx(400.0)

    async def test_sell_closes_long_position(
        self, manager: PositionManager, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="SELL",
                fill_price=160.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.drain()

        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 0
        assert pos.avg_cost == 0.0
        assert pos.realized_pnl == pytest.approx(1000.0)

        closed = [e for e in collected_events if isinstance(e, PositionClosedEvent)]
        assert len(closed) >= 1
        assert closed[0].symbol == "AAPL"
        assert closed[0].realized_pnl == pytest.approx(1000.0)

    async def test_sell_opens_short_position(
        self, manager: PositionManager, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="SELL",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.drain()

        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == -100
        assert pos.avg_cost == 150.0
        assert pos.realized_pnl == 0.0

        opened = [e for e in collected_events if isinstance(e, PositionOpenedEvent)]
        assert len(opened) >= 1
        assert opened[0].quantity == -100

    async def test_buy_reduces_short_position(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="SELL",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="BUY",
                fill_price=140.0,
                fill_quantity=40,
                source="test",
            )
        )
        await event_bus.drain()

        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == -60
        assert pos.avg_cost == 150.0
        assert pos.realized_pnl == pytest.approx(400.0)

    async def test_buy_closes_short_position(
        self, manager: PositionManager, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="SELL",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="BUY",
                fill_price=140.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.drain()

        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 0
        assert pos.avg_cost == 0.0
        assert pos.realized_pnl == pytest.approx(1000.0)

        closed = [e for e in collected_events if isinstance(e, PositionClosedEvent)]
        assert len(closed) >= 1
        assert closed[0].symbol == "AAPL"

    async def test_sell_exceeds_long_creates_short(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="SELL",
                fill_price=160.0,
                fill_quantity=150,
                source="test",
            )
        )
        await event_bus.drain()

        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == -50
        assert pos.avg_cost == 160.0
        assert pos.realized_pnl == pytest.approx(1000.0)

    async def test_buy_exceeds_short_creates_long(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="SELL",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="BUY",
                fill_price=140.0,
                fill_quantity=150,
                source="test",
            )
        )
        await event_bus.drain()

        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 50
        assert pos.avg_cost == 140.0
        assert pos.realized_pnl == pytest.approx(1000.0)

    async def test_multiple_symbols_independent(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="MSFT",
                side="BUY",
                fill_price=300.0,
                fill_quantity=50,
                source="test",
            )
        )
        await event_bus.drain()

        assert len(manager.positions) == 2
        assert manager.positions["AAPL"].quantity == 100
        assert manager.positions["MSFT"].quantity == 50

    async def test_fill_before_start_ignored(self, event_bus: EventBus) -> None:
        m = PositionManager(event_bus=event_bus)
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.drain()
        assert len(m.positions) == 0


class TestPositionManagerPnL:
    async def test_realized_pnl_long(self, manager: PositionManager, event_bus: EventBus) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="SELL",
                fill_price=170.0,
                fill_quantity=50,
                source="test",
            )
        )
        await event_bus.drain()
        assert manager.total_realized_pnl == pytest.approx(1000.0)

    async def test_realized_pnl_short(self, manager: PositionManager, event_bus: EventBus) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="SELL",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="BUY",
                fill_price=130.0,
                fill_quantity=50,
                source="test",
            )
        )
        await event_bus.drain()
        assert manager.total_realized_pnl == pytest.approx(1000.0)

    async def test_total_pnl_combines_realized_and_unrealized(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.drain()
        realized = manager.total_realized_pnl
        unrealized = manager.total_unrealized_pnl
        assert manager.total_pnl == pytest.approx(realized + unrealized)

    async def test_unrealized_pnl_updates_on_tick(
        self, manager: PositionManager, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=160.0, source="test"))
        await event_bus.drain()

        assert manager.total_unrealized_pnl == pytest.approx(1000.0)

        pnl_events = [e for e in collected_events if isinstance(e, PnLUpdatedEvent)]
        aapl_pnl = [e for e in pnl_events if e.symbol == "AAPL"]
        assert len(aapl_pnl) >= 1
        assert aapl_pnl[-1].unrealized_pnl == pytest.approx(1000.0)

    async def test_pnl_updated_emitted_on_fill(
        self, manager: PositionManager, collected_events: list, event_bus: EventBus
    ) -> None:
        assert manager.is_running is True
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.drain()
        pnl_events = [e for e in collected_events if isinstance(e, PnLUpdatedEvent)]
        assert len(pnl_events) >= 1

    async def test_equity_includes_pnl(self, manager: PositionManager, event_bus: EventBus) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=160.0, source="test"))
        await event_bus.drain()
        assert manager.equity == pytest.approx(100_000.0 + manager.total_pnl)


class TestPositionManagerTickHandling:
    async def test_tick_updates_market_price(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=155.0, source="test"))
        await event_bus.drain()
        assert manager._market_prices["AAPL"] == 155.0

    async def test_tick_with_bid_ask(self, manager: PositionManager, event_bus: EventBus) -> None:
        await event_bus.publish(MarketTickEvent(symbol="AAPL", bid=154.0, ask=156.0, source="test"))
        await event_bus.drain()
        assert manager._market_prices["AAPL"] == 155.0

    async def test_tick_before_start_ignored(self, event_bus: EventBus) -> None:
        m = PositionManager(event_bus=event_bus)
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=155.0, source="test"))
        await event_bus.drain()
        assert "AAPL" not in m._market_prices

    async def test_tick_emits_position_update(
        self, manager: PositionManager, collected_events: list, event_bus: EventBus
    ) -> None:
        assert manager.is_running is True
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=155.0, source="test"))
        await event_bus.drain()

        updates = [e for e in collected_events if isinstance(e, PositionUpdate)]
        aapl_updates = [u for u in updates if u.symbol == "AAPL"]
        assert len(aapl_updates) >= 1
        assert aapl_updates[-1].position == 100
        assert aapl_updates[-1].avg_cost == 150.0
        assert aapl_updates[-1].market_price == 155.0


class TestPositionManagerExposure:
    async def test_no_positions(self, manager: PositionManager) -> None:
        exp = manager.exposure()
        assert exp.gross_exposure == 0.0
        assert exp.net_exposure == 0.0
        assert exp.long_count == 0
        assert exp.short_count == 0

    async def test_long_exposure(self, manager: PositionManager, event_bus: EventBus) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=160.0, source="test"))
        await event_bus.drain()
        exp = manager.exposure()
        assert exp.gross_exposure == pytest.approx(160.0 * 100)
        assert exp.net_exposure == pytest.approx(160.0 * 100)
        assert exp.long_count == 1
        assert exp.short_count == 0

    async def test_short_exposure(self, manager: PositionManager, event_bus: EventBus) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="SELL",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=140.0, source="test"))
        await event_bus.drain()
        exp = manager.exposure()
        assert exp.gross_exposure == pytest.approx(140.0 * 100)
        assert exp.net_exposure == pytest.approx(-140.0 * 100)
        assert exp.long_count == 0
        assert exp.short_count == 1

    async def test_mixed_exposure(self, manager: PositionManager, event_bus: EventBus) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="MSFT",
                side="SELL",
                fill_price=300.0,
                fill_quantity=50,
                source="test",
            )
        )
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=160.0, source="test"))
        await event_bus.publish(MarketTickEvent(symbol="MSFT", price=290.0, source="test"))
        await event_bus.drain()
        exp = manager.exposure()
        assert exp.gross_exposure == pytest.approx((160.0 * 100) + (290.0 * 50))
        assert exp.net_exposure == pytest.approx((160.0 * 100) - (290.0 * 50))
        assert exp.long_count == 1
        assert exp.short_count == 1

    async def test_leverage(self, manager: PositionManager, event_bus: EventBus) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=150.0, source="test"))
        await event_bus.drain()
        expected_leverage = (150.0 * 100) / 100_000.0
        assert manager.leverage == pytest.approx(expected_leverage)

    async def test_leverage_zero_when_no_equity(self, event_bus: EventBus) -> None:
        m = PositionManager(event_bus=event_bus, initial_capital=0.0)
        await m.start()
        assert m.leverage == 0.0
        await m.stop()


class TestPositionManagerPersistence:
    async def test_persists_position_with_db_manager(
        self, event_bus: EventBus, tmp_path: object
    ) -> None:
        from pathlib import Path

        from trading_platform.persistence.database import DatabaseManager
        from trading_platform.persistence.models import PositionRecord

        db_path = Path(tmp_path) / "test_portfolio.db"
        db = DatabaseManager(f"sqlite:///{db_path}")
        db.init_db()
        m = PositionManager(event_bus=event_bus, db_manager=db, initial_capital=100_000.0)
        await m.start()

        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.drain()
        await m.stop()

        with db.session() as session:
            record = session.query(PositionRecord).filter_by(symbol="AAPL").first()
            assert record is not None
            assert record.quantity == 100
            assert record.avg_cost == 150.0

        db.close()

    async def test_updates_existing_position(self, event_bus: EventBus, tmp_path: object) -> None:
        from pathlib import Path

        from trading_platform.persistence.database import DatabaseManager
        from trading_platform.persistence.models import PositionRecord

        db_path = Path(tmp_path) / "test_portfolio2.db"
        db = DatabaseManager(f"sqlite:///{db_path}")
        db.init_db()
        m = PositionManager(event_bus=event_bus, db_manager=db, initial_capital=100_000.0)
        await m.start()

        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.publish(
            OrderFilledEvent(
                order_id="2",
                symbol="AAPL",
                side="BUY",
                fill_price=160.0,
                fill_quantity=50,
                source="test",
            )
        )
        await event_bus.drain()
        await m.stop()

        with db.session() as session:
            record = session.query(PositionRecord).filter_by(symbol="AAPL").first()
            assert record is not None
            expected_avg = ((150.0 * 100) + (160.0 * 50)) / 150
            assert record.quantity == 150
            assert record.avg_cost == pytest.approx(expected_avg)

        db.close()

    async def test_no_db_manager_does_not_crash(
        self, manager: PositionManager, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0,
                fill_quantity=100,
                source="test",
            )
        )
        await event_bus.drain()
        pos = manager.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 100
