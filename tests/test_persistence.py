from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from edrader.persistence.database import DatabaseManager
from edrader.persistence.models import (
    FillRecord,
    OrderRecord,
    PnlSnapshotRecord,
    PositionRecord,
)


@pytest.fixture
def db_manager(tmp_path: Path) -> DatabaseManager:
    db_path = tmp_path / "test.db"
    mgr = DatabaseManager(f"sqlite:///{db_path}")
    mgr.init_db()
    yield mgr
    mgr.close()


class TestDatabaseManager:
    async def test_init_db_creates_tables(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        mgr = DatabaseManager(f"sqlite:///{db_path}")
        mgr.init_db()
        assert mgr.is_initialized is True
        mgr.close()

    async def test_init_db_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        mgr = DatabaseManager(f"sqlite:///{db_path}")
        mgr.init_db()
        mgr.init_db()
        assert mgr.is_initialized is True
        mgr.close()

    async def test_close_disposes_engine(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        mgr = DatabaseManager(f"sqlite:///{db_path}")
        mgr.init_db()
        mgr.close()
        assert mgr.is_initialized is False

    async def test_session_commit(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        with db_manager.session() as session:
            record = OrderRecord(
                order_id="test-1",
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                created_at=now,
                updated_at=now,
            )
            session.add(record)

        with db_manager.session() as session:
            saved = session.query(OrderRecord).filter_by(order_id="test-1").first()
            assert saved is not None
            assert saved.symbol == "AAPL"
            assert saved.quantity == 100

    async def test_session_rollback_on_error(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        with (
            pytest.raises(RuntimeError),
            db_manager.session() as session,
        ):
            record = OrderRecord(
                order_id="test-rollback",
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            raise RuntimeError("force rollback")

        with db_manager.session() as session:
            saved = session.query(OrderRecord).filter_by(order_id="test-rollback").first()
            assert saved is None


class TestOrderRecord:
    def _make_order(
        self,
        order_id: str = "ord-1",
        symbol: str = "AAPL",
        side: str = "BUY",
        quantity: int = 100,
        order_type: str = "MKT",
        status: str = "Submitted",
    ) -> None:
        now = datetime.now(UTC)
        self._order = OrderRecord(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            status=status,
            created_at=now,
            updated_at=now,
        )

    async def test_create_order(self, db_manager: DatabaseManager) -> None:
        self._make_order()
        with db_manager.session() as session:
            session.add(self._order)

        with db_manager.session() as session:
            saved = session.query(OrderRecord).filter_by(order_id="ord-1").first()
            assert saved is not None
            assert saved.symbol == "AAPL"
            assert saved.side == "BUY"
            assert saved.quantity == 100
            assert saved.order_type == "MKT"
            assert saved.status == "Submitted"
            assert saved.filled_quantity == 0
            assert saved.limit_price is None

    async def test_create_order_with_limit(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        record = OrderRecord(
            order_id="ord-lmt",
            symbol="MSFT",
            side="SELL",
            quantity=50,
            order_type="LMT",
            limit_price=155.0,
            created_at=now,
            updated_at=now,
        )
        with db_manager.session() as session:
            session.add(record)

        with db_manager.session() as session:
            saved = session.query(OrderRecord).filter_by(order_id="ord-lmt").first()
            assert saved is not None
            assert saved.limit_price == 155.0
            assert saved.order_type == "LMT"

    async def test_unique_order_id(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        record1 = OrderRecord(
            order_id="dup",
            symbol="AAPL",
            side="BUY",
            quantity=100,
            order_type="MKT",
            created_at=now,
            updated_at=now,
        )
        record2 = OrderRecord(
            order_id="dup",
            symbol="MSFT",
            side="SELL",
            quantity=50,
            order_type="MKT",
            created_at=now,
            updated_at=now,
        )
        with db_manager.session() as session:
            session.add(record1)
        with (
            pytest.raises(IntegrityError),
            db_manager.session() as session,
        ):
            session.add(record2)

    async def test_query_by_symbol(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        for sym in ["AAPL", "MSFT", "GOOG"]:
            record = OrderRecord(
                order_id=f"ord-{sym}",
                symbol=sym,
                side="BUY",
                quantity=100,
                order_type="MKT",
                created_at=now,
                updated_at=now,
            )
            with db_manager.session() as session:
                session.add(record)

        with db_manager.session() as session:
            results = session.query(OrderRecord).filter_by(symbol="AAPL").all()
            assert len(results) == 1
            assert results[0].order_id == "ord-AAPL"

    async def test_update_order_status(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        with db_manager.session() as session:
            record = OrderRecord(
                order_id="ord-upd",
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                created_at=now,
                updated_at=now,
            )
            session.add(record)

        with db_manager.session() as session:
            saved = session.query(OrderRecord).filter_by(order_id="ord-upd").first()
            assert saved is not None
            saved.status = "Filled"
            saved.filled_quantity = 100
            saved.updated_at = datetime.now(UTC)

        with db_manager.session() as session:
            saved = session.query(OrderRecord).filter_by(order_id="ord-upd").first()
            assert saved is not None
            assert saved.status == "Filled"
            assert saved.filled_quantity == 100


class TestFillRecord:
    async def test_create_fill(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        fill = FillRecord(
            order_id="ord-1",
            symbol="AAPL",
            side="BUY",
            fill_price=150.25,
            fill_quantity=100,
            fill_time=now,
        )
        with db_manager.session() as session:
            session.add(fill)

        with db_manager.session() as session:
            saved = session.query(FillRecord).filter_by(order_id="ord-1").first()
            assert saved is not None
            assert saved.fill_price == 150.25
            assert saved.fill_quantity == 100
            assert saved.symbol == "AAPL"

    async def test_multiple_fills_per_order(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        for i in range(3):
            fill = FillRecord(
                order_id="ord-partial",
                symbol="AAPL",
                side="BUY",
                fill_price=150.0 + i,
                fill_quantity=33,
                fill_time=now,
            )
            with db_manager.session() as session:
                session.add(fill)

        with db_manager.session() as session:
            fills = session.query(FillRecord).filter_by(order_id="ord-partial").all()
            assert len(fills) == 3

    async def test_fill_has_created_at(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        fill = FillRecord(
            order_id="ord-ts",
            symbol="AAPL",
            side="BUY",
            fill_price=150.0,
            fill_quantity=100,
            fill_time=now,
        )
        with db_manager.session() as session:
            session.add(fill)

        with db_manager.session() as session:
            saved = session.query(FillRecord).filter_by(order_id="ord-ts").first()
            assert saved is not None
            assert saved.created_at is not None


class TestPositionRecord:
    async def test_create_position(self, db_manager: DatabaseManager) -> None:
        record = PositionRecord(
            symbol="AAPL",
            quantity=100,
            avg_cost=150.25,
        )
        with db_manager.session() as session:
            session.add(record)

        with db_manager.session() as session:
            saved = session.query(PositionRecord).filter_by(symbol="AAPL").first()
            assert saved is not None
            assert saved.quantity == 100
            assert saved.avg_cost == 150.25

    async def test_unique_symbol(self, db_manager: DatabaseManager) -> None:
        with db_manager.session() as session:
            session.add(PositionRecord(symbol="AAPL", quantity=100, avg_cost=150.0))
        with (
            pytest.raises(IntegrityError),
            db_manager.session() as session,
        ):
            session.add(PositionRecord(symbol="AAPL", quantity=50, avg_cost=151.0))

    async def test_update_position(self, db_manager: DatabaseManager) -> None:
        with db_manager.session() as session:
            session.add(PositionRecord(symbol="AAPL", quantity=100, avg_cost=150.0))

        with db_manager.session() as session:
            pos = session.query(PositionRecord).filter_by(symbol="AAPL").first()
            assert pos is not None
            pos.quantity = 200
            pos.avg_cost = 151.0

        with db_manager.session() as session:
            pos = session.query(PositionRecord).filter_by(symbol="AAPL").first()
            assert pos is not None
            assert pos.quantity == 200
            assert pos.avg_cost == 151.0

    async def test_short_position(self, db_manager: DatabaseManager) -> None:
        with db_manager.session() as session:
            session.add(PositionRecord(symbol="MSFT", quantity=-50, avg_cost=300.0))

        with db_manager.session() as session:
            pos = session.query(PositionRecord).filter_by(symbol="MSFT").first()
            assert pos is not None
            assert pos.quantity == -50

    async def test_position_has_updated_at(self, db_manager: DatabaseManager) -> None:
        with db_manager.session() as session:
            session.add(PositionRecord(symbol="AAPL", quantity=100, avg_cost=150.0))

        with db_manager.session() as session:
            pos = session.query(PositionRecord).filter_by(symbol="AAPL").first()
            assert pos is not None
            assert pos.updated_at is not None


class TestPnlSnapshotRecord:
    async def test_create_snapshot(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        snapshot = PnlSnapshotRecord(
            symbol="AAPL",
            unrealized_pnl=500.0,
            realized_pnl=100.0,
            snapshot_time=now,
        )
        with db_manager.session() as session:
            session.add(snapshot)

        with db_manager.session() as session:
            saved = session.query(PnlSnapshotRecord).filter_by(symbol="AAPL").first()
            assert saved is not None
            assert saved.unrealized_pnl == 500.0
            assert saved.realized_pnl == 100.0

    async def test_multiple_snapshots_per_symbol(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        for i in range(5):
            snapshot = PnlSnapshotRecord(
                symbol="AAPL",
                unrealized_pnl=float(i * 100),
                realized_pnl=0.0,
                snapshot_time=now,
            )
            with db_manager.session() as session:
                session.add(snapshot)

        with db_manager.session() as session:
            snapshots = session.query(PnlSnapshotRecord).filter_by(symbol="AAPL").all()
            assert len(snapshots) == 5

    async def test_snapshot_has_created_at(self, db_manager: DatabaseManager) -> None:
        now = datetime.now(UTC)
        with db_manager.session() as session:
            session.add(
                PnlSnapshotRecord(
                    symbol="AAPL",
                    unrealized_pnl=0.0,
                    realized_pnl=0.0,
                    snapshot_time=now,
                )
            )

        with db_manager.session() as session:
            saved = session.query(PnlSnapshotRecord).filter_by(symbol="AAPL").first()
            assert saved is not None
            assert saved.created_at is not None
