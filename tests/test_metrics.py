from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    ExposureUpdatedEvent,
    OrderFilledEvent,
    PositionClosedEvent,
)
from edrader.replay.metrics import BacktestMetrics, MetricsEngine


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
async def engine(event_bus: EventBus) -> MetricsEngine:
    e = MetricsEngine(event_bus=event_bus)
    await e.start()
    yield e
    await e.stop()


def _ts(offset_seconds: float = 0) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=offset_seconds)


class TestMetricsEngineLifecycle:
    async def test_initial_state(self, engine: MetricsEngine) -> None:
        assert engine.is_running is True
        metrics = engine.compute()
        assert metrics.total_return == 0.0
        assert metrics.sharpe_ratio == 0.0
        assert metrics.max_drawdown == 0.0
        assert metrics.win_rate == 0.0
        assert metrics.total_trades == 0

    async def test_start_sets_running(self, event_bus: EventBus) -> None:
        e = MetricsEngine(event_bus=event_bus)
        assert e.is_running is False
        await e.start()
        assert e.is_running is True
        await e.stop()

    async def test_stop_clears_running(self, engine: MetricsEngine) -> None:
        assert engine.is_running is True
        await engine.stop()
        assert engine.is_running is False

    async def test_start_idempotent(self, engine: MetricsEngine) -> None:
        await engine.start()
        assert engine.is_running is True

    async def test_stop_idempotent(self, engine: MetricsEngine) -> None:
        await engine.stop()
        await engine.stop()
        assert engine.is_running is False

    async def test_subscribes_to_exposure_updates(
        self,
        engine: MetricsEngine,
        event_bus: EventBus,  # noqa: ARG002
    ) -> None:
        assert event_bus.subscriber_count_for(ExposureUpdatedEvent) >= 1

    async def test_subscribes_to_fills(
        self,
        engine: MetricsEngine,
        event_bus: EventBus,  # noqa: ARG002
    ) -> None:
        assert event_bus.subscriber_count_for(OrderFilledEvent) >= 1

    async def test_subscribes_to_position_closes(
        self,
        engine: MetricsEngine,
        event_bus: EventBus,  # noqa: ARG002
    ) -> None:
        assert event_bus.subscriber_count_for(PositionClosedEvent) >= 1


class TestMetricsEngineEquityTracking:
    async def test_records_equity_from_exposure_event(
        self, engine: MetricsEngine, event_bus: EventBus
    ) -> None:
        ts = _ts()
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=ts,
                source="test",
            )
        )
        await event_bus.drain()

        assert len(engine._equity_curve) >= 1
        assert engine._equity_curve[0][1] == 100_000.0

    async def test_records_multiple_equity_points(
        self, engine: MetricsEngine, event_bus: EventBus
    ) -> None:
        for i in range(5):
            await event_bus.publish(
                ExposureUpdatedEvent(
                    gross_exposure=0.0,
                    net_exposure=0.0,
                    leverage=0.0,
                    long_count=0,
                    short_count=0,
                    equity=100_000.0 + i * 1000.0,
                    timestamp=_ts(i),
                    source="test",
                )
            )
        await event_bus.drain()

        assert len(engine._equity_curve) == 5
        assert engine._equity_curve[-1][1] == 104_000.0

    async def test_ignores_exposure_before_start(self, event_bus: EventBus) -> None:
        e = MetricsEngine(event_bus=event_bus)
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=50_000.0,
                timestamp=_ts(),
                source="test",
            )
        )
        await event_bus.drain()
        assert len(e._equity_curve) == 0


class TestMetricsEngineTotalReturn:
    async def test_positive_return(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=_ts(0),
                source="test",
            )
        )
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=110_000.0,
                timestamp=_ts(1),
                source="test",
            )
        )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.total_return == pytest.approx(0.10)

    async def test_negative_return(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=_ts(0),
                source="test",
            )
        )
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=90_000.0,
                timestamp=_ts(1),
                source="test",
            )
        )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.total_return == pytest.approx(-0.10)

    async def test_zero_return(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=_ts(0),
                source="test",
            )
        )
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=_ts(1),
                source="test",
            )
        )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.total_return == 0.0


class TestMetricsEngineAnnualizedReturn:
    async def test_annualized_return_over_one_year(
        self, engine: MetricsEngine, event_bus: EventBus
    ) -> None:
        ts0 = _ts(0)
        ts1 = ts0 + timedelta(days=365)
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=ts0,
                source="test",
            )
        )
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=110_000.0,
                timestamp=ts1,
                source="test",
            )
        )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.annualized_return == pytest.approx(0.10, rel=0.01)

    async def test_annualized_return_over_six_months(
        self, engine: MetricsEngine, event_bus: EventBus
    ) -> None:
        ts0 = _ts(0)
        ts1 = ts0 + timedelta(days=182)
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=ts0,
                source="test",
            )
        )
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=110_000.0,
                timestamp=ts1,
                source="test",
            )
        )
        await event_bus.drain()

        metrics = engine.compute()
        expected_annualized = (1 + 0.10) ** (1 / (182 / 365.25)) - 1
        assert metrics.annualized_return == pytest.approx(expected_annualized, rel=0.01)


class TestMetricsEngineWinRate:
    async def test_all_wins(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        for _ in range(3):
            await event_bus.publish(
                PositionClosedEvent(symbol="AAPL", realized_pnl=100.0, source="test")
            )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.win_rate == 1.0
        assert metrics.total_trades == 3
        assert metrics.winning_trades == 3
        assert metrics.losing_trades == 0

    async def test_all_losses(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        for _ in range(3):
            await event_bus.publish(
                PositionClosedEvent(symbol="AAPL", realized_pnl=-100.0, source="test")
            )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.win_rate == 0.0
        assert metrics.total_trades == 3
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 3

    async def test_mixed_wins_and_losses(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        for pnl in [100.0, -50.0, 200.0, -30.0, 10.0]:
            await event_bus.publish(
                PositionClosedEvent(symbol="AAPL", realized_pnl=pnl, source="test")
            )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.win_rate == pytest.approx(3 / 5)
        assert metrics.total_trades == 5
        assert metrics.winning_trades == 3
        assert metrics.losing_trades == 2

    async def test_zero_pnl_not_counted_as_win_or_loss(
        self, engine: MetricsEngine, event_bus: EventBus
    ) -> None:
        await event_bus.publish(PositionClosedEvent(symbol="AAPL", realized_pnl=0.0, source="test"))
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.total_trades == 0
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 0


class TestMetricsEngineMaxDrawdown:
    async def test_no_drawdown_monotonic_up(
        self, engine: MetricsEngine, event_bus: EventBus
    ) -> None:
        for i in range(5):
            await event_bus.publish(
                ExposureUpdatedEvent(
                    gross_exposure=0.0,
                    net_exposure=0.0,
                    leverage=0.0,
                    long_count=0,
                    short_count=0,
                    equity=100_000.0 + i * 5000.0,
                    timestamp=_ts(i),
                    source="test",
                )
            )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.max_drawdown == 0.0
        assert metrics.peak_equity == 120_000.0

    async def test_drawdown_computed_correctly(
        self, engine: MetricsEngine, event_bus: EventBus
    ) -> None:
        equities = [100_000.0, 110_000.0, 105_000.0, 115_000.0, 95_000.0, 105_000.0]
        for i, eq in enumerate(equities):
            await event_bus.publish(
                ExposureUpdatedEvent(
                    gross_exposure=0.0,
                    net_exposure=0.0,
                    leverage=0.0,
                    long_count=0,
                    short_count=0,
                    equity=eq,
                    timestamp=_ts(i),
                    source="test",
                )
            )
        await event_bus.drain()

        metrics = engine.compute()
        max_dd_expected = (115_000.0 - 95_000.0) / 115_000.0
        assert metrics.max_drawdown == pytest.approx(max_dd_expected)
        assert metrics.peak_equity == 115_000.0

    async def test_all_down_only_drawdown(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        equities = [100_000.0, 90_000.0, 80_000.0]
        for i, eq in enumerate(equities):
            await event_bus.publish(
                ExposureUpdatedEvent(
                    gross_exposure=0.0,
                    net_exposure=0.0,
                    leverage=0.0,
                    long_count=0,
                    short_count=0,
                    equity=eq,
                    timestamp=_ts(i),
                    source="test",
                )
            )
        await event_bus.drain()

        metrics = engine.compute()
        expected = (100_000.0 - 80_000.0) / 100_000.0
        assert metrics.max_drawdown == pytest.approx(expected)


class TestMetricsEngineTurnover:
    async def test_turnover_computed(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=_ts(0),
                source="test",
            )
        )
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
        await event_bus.drain()

        metrics = engine.compute()
        expected_turnover = (150.0 * 100 + 300.0 * 50) / 100_000.0
        assert metrics.turnover == pytest.approx(expected_turnover)


class TestMetricsEngineSharpeRatio:
    async def test_sharpe_positive(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        ts0 = _ts(0)
        ts1 = ts0 + timedelta(days=1)
        ts2 = ts1 + timedelta(days=1)
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=ts0,
                source="test",
            )
        )
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=101_000.0,
                timestamp=ts1,
                source="test",
            )
        )
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=102_000.0,
                timestamp=ts2,
                source="test",
            )
        )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.sharpe_ratio > 0

    async def test_sharpe_negative(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        ts0 = _ts(0)
        ts1 = ts0 + timedelta(days=1)
        ts2 = ts1 + timedelta(days=1)
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=ts0,
                source="test",
            )
        )
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=99_000.0,
                timestamp=ts1,
                source="test",
            )
        )
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=98_000.0,
                timestamp=ts2,
                source="test",
            )
        )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.sharpe_ratio < 0


class TestMetricsEngineEdgeCases:
    async def test_no_events_returns_empty_metrics(self, engine: MetricsEngine) -> None:
        metrics = engine.compute()
        assert metrics.total_return == 0.0
        assert metrics.sharpe_ratio == 0.0
        assert metrics.max_drawdown == 0.0
        assert metrics.win_rate == 0.0
        assert metrics.turnover == 0.0
        assert metrics.total_trades == 0

    async def test_single_event_no_curve(self, engine: MetricsEngine, event_bus: EventBus) -> None:
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                timestamp=_ts(0),
                source="test",
            )
        )
        await event_bus.drain()

        metrics = engine.compute()
        assert metrics.start_equity == 100_000.0
        assert metrics.end_equity == 100_000.0
        assert metrics.max_drawdown == 0.0


class TestMetricsEngineFields:
    async def test_backtest_metrics_dataclass(self) -> None:
        m = BacktestMetrics(
            total_return=0.15,
            annualized_return=0.10,
            sharpe_ratio=1.5,
            max_drawdown=0.05,
            win_rate=0.6,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            turnover=2.5,
            start_equity=100_000.0,
            end_equity=115_000.0,
            peak_equity=120_000.0,
        )
        assert m.total_return == 0.15
        assert m.sharpe_ratio == 1.5
        assert m.total_trades == 10
