from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BarCloseEvent,
    MarketTickEvent,
    OrderFilledEvent,
    OrderRequestedEvent,
    OrderSubmittedEvent,
    SignalApprovedEvent,
    SignalGeneratedEvent,
    SignalRejectedEvent,
)
from edrader.execution.engine import ExecutionEngine
from edrader.portfolio.position import PositionManager
from edrader.replay.metrics import MetricsEngine
from edrader.replay.simulated_broker import SimulatedBroker
from edrader.risk.engine import RiskEngine


@pytest.fixture
async def event_bus() -> EventBus:
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
def collected_events(event_bus: EventBus) -> list[object]:
    events: list[object] = []

    async def collector(event: object) -> None:
        events.append(event)

    event_bus.subscribe_all(collector, name="collector")
    return events


def _ts(offset_days: float = 0) -> datetime:
    return datetime.now(UTC) + timedelta(days=offset_days)


class TestSignalToFillPipeline:
    async def test_signal_through_risk_to_execution_to_broker(
        self, event_bus: EventBus, collected_events: list[object]
    ) -> None:
        pm = PositionManager(event_bus=event_bus)
        risk = RiskEngine(event_bus=event_bus, position_manager=pm)
        exec_eng = ExecutionEngine(event_bus=event_bus, throttle_delay=0.0)
        broker = SimulatedBroker(event_bus=event_bus)

        await risk.start()
        await exec_eng.start()
        await broker.start()
        await pm.start()

        await event_bus.publish(
            MarketTickEvent(symbol="AAPL", price=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test_strat",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        approved = [e for e in collected_events if isinstance(e, SignalApprovedEvent)]
        assert len(approved) >= 1

        requested = [e for e in collected_events if isinstance(e, OrderRequestedEvent)]
        assert len(requested) >= 1
        req = requested[-1]
        assert req.symbol == "AAPL"
        assert req.side == "BUY"
        assert req.quantity == 100

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        fill = filled[-1]
        assert fill.symbol == "AAPL"
        assert fill.side == "BUY"
        assert fill.fill_quantity == 100

        pos = pm.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 100

        await risk.stop()
        await exec_eng.stop()
        await broker.stop()
        await pm.stop()

    async def test_signal_to_fill_with_rejected_signal(
        self, event_bus: EventBus, collected_events: list[object]
    ) -> None:
        pm = PositionManager(event_bus=event_bus)
        risk = RiskEngine(event_bus=event_bus, position_manager=pm, max_position_size=10)
        await risk.start()
        await pm.start()

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test_strat",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=9999,
                source="test",
            )
        )
        await event_bus.drain()

        approved = [e for e in collected_events if isinstance(e, SignalApprovedEvent)]
        assert len(approved) == 0

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) >= 1

        await risk.stop()
        await pm.stop()


class TestFullPipelineWithMetrics:
    async def test_metrics_captures_equity_after_fill(self, event_bus: EventBus) -> None:
        broker = SimulatedBroker(event_bus=event_bus)
        pm = PositionManager(event_bus=event_bus)
        metrics = MetricsEngine(event_bus=event_bus)

        await broker.start()
        await pm.start()
        await metrics.start()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        result = metrics.compute()
        assert result.total_trades == 0
        assert result.start_equity > 0
        assert result.end_equity > 0

        await broker.stop()
        await pm.stop()
        await metrics.stop()

    async def test_metrics_after_full_trade_cycle(self, event_bus: EventBus) -> None:
        broker = SimulatedBroker(event_bus=event_bus, commission_per_trade=1.50)
        pm = PositionManager(event_bus=event_bus)
        metrics = MetricsEngine(event_bus=event_bus)

        await broker.start()
        await pm.start()
        await metrics.start()

        ts0 = _ts(0)
        ts1 = _ts(1)
        ts2 = _ts(2)

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=100.0, timestamp=ts0, source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=10,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=110.0, timestamp=ts1, source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="SELL",
                quantity=10,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=110.0, timestamp=ts2, source="test")
        )
        await event_bus.drain()

        result = metrics.compute()
        assert result.total_trades >= 1
        assert result.winning_trades >= 1

        await broker.stop()
        await pm.stop()
        await metrics.stop()


class TestDeterministicBacktest:
    async def test_deterministic_market_order_flow(self, event_bus: EventBus) -> None:
        broker = SimulatedBroker(event_bus=event_bus, slippage_bps=0.0, commission_per_trade=0.0)
        pm = PositionManager(event_bus=event_bus)
        metrics = MetricsEngine(event_bus=event_bus)

        await broker.start()
        await pm.start()
        await metrics.start()

        ts0 = _ts(0)
        ts1 = _ts(1)

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=100.0, timestamp=ts0, source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=10,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=110.0, timestamp=ts1, source="test")
        )
        await event_bus.drain()

        pos = pm.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 10
        assert pos.avg_cost == 100.0

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="SELL",
                quantity=10,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        pos = pm.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 0
        assert pos.realized_pnl == pytest.approx(100.0)

        await broker.stop()
        await pm.stop()
        await metrics.stop()

    async def test_deterministic_limit_order_flow(self, event_bus: EventBus) -> None:
        broker = SimulatedBroker(event_bus=event_bus, slippage_bps=0.0, commission_per_trade=0.0)
        pm = PositionManager(event_bus=event_bus)

        await broker.start()
        await pm.start()

        ts0 = _ts(0)
        ts1 = ts0 + timedelta(seconds=1)

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=100.0, timestamp=ts0, source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=10,
                order_type="LMT",
                limit_price=95.0,
                source="test",
            )
        )
        await event_bus.drain()

        assert broker.active_order_ids != []

        await event_bus.publish(
            MarketTickEvent(symbol="AAPL", price=94.0, timestamp=ts1, source="test")
        )
        await event_bus.drain()

        pos = pm.positions.get("AAPL")
        assert pos is not None
        assert pos.quantity == 10
        assert pos.avg_cost == 95.0

        await broker.stop()
        await pm.stop()


class TestPipelineEdgeCases:
    async def test_order_before_price_deferred(
        self, event_bus: EventBus, collected_events: list[object]
    ) -> None:
        broker = SimulatedBroker(event_bus=event_bus)
        await broker.start()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled_before_price = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled_before_price) == 0

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        filled_after_price = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled_after_price) >= 1
        assert filled_after_price[-1].fill_price == 150.0

        await broker.stop()

    async def test_multiple_symbols_independent_pipeline(self, event_bus: EventBus) -> None:
        broker = SimulatedBroker(event_bus=event_bus)
        pm = PositionManager(event_bus=event_bus)

        await broker.start()
        await pm.start()

        ts0 = _ts(0)
        ts1 = _ts(1)

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=100.0, timestamp=ts0, source="test")
        )
        await event_bus.publish(
            BarCloseEvent(symbol="MSFT", close=200.0, timestamp=ts0, source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=10,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="MSFT",
                side="SELL",
                quantity=5,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=110.0, timestamp=ts1, source="test")
        )
        await event_bus.publish(
            BarCloseEvent(symbol="MSFT", close=190.0, timestamp=ts1, source="test")
        )
        await event_bus.drain()

        aapl = pm.positions.get("AAPL")
        msft = pm.positions.get("MSFT")
        assert aapl is not None and aapl.quantity == 10
        assert msft is not None and msft.quantity == -5

        exposure = pm.exposure()
        assert exposure.long_count == 1
        assert exposure.short_count == 1

        await broker.stop()
        await pm.stop()

    async def test_pipeline_handles_new_symbol_gracefully(
        self, event_bus: EventBus, collected_events: list[object]
    ) -> None:
        broker = SimulatedBroker(event_bus=event_bus)
        pm = PositionManager(event_bus=event_bus)

        await broker.start()
        await pm.start()

        ts0 = _ts(0)

        await event_bus.publish(
            BarCloseEvent(symbol="NEW", close=50.0, timestamp=ts0, source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="NEW",
                side="BUY",
                quantity=10,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        submitted = [e for e in collected_events if isinstance(e, OrderSubmittedEvent)]
        assert len(submitted) >= 1

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1

        pos = pm.positions.get("NEW")
        assert pos is not None
        assert pos.quantity == 10

        await event_bus.publish(
            BarCloseEvent(symbol="NEW", close=55.0, timestamp=ts0, source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="NEW",
                side="SELL",
                quantity=10,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        pos = pm.positions.get("NEW")
        assert pos is not None
        assert pos.quantity == 0
        assert pos.realized_pnl == pytest.approx(50.0)

        await broker.stop()
        await pm.stop()
