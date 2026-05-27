from __future__ import annotations

import pytest

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BrokerDisconnectedEvent,
    ExposureUpdatedEvent,
    MarketTickEvent,
    OrderFilledEvent,
    RiskViolationEvent,
    SignalApprovedEvent,
    SignalGeneratedEvent,
    SignalRejectedEvent,
    TradingHaltedEvent,
)
from edrader.risk.engine import RiskEngine


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
async def engine(event_bus: EventBus) -> RiskEngine:
    e = RiskEngine(event_bus=event_bus)
    await e.start()
    yield e
    await e.stop()


class TestRiskEngineLifecycle:
    async def test_initial_state(self, engine: RiskEngine) -> None:
        assert engine.is_running is True
        assert engine.kill_switch_active is False
        assert engine.daily_realized_pnl == 0.0

    async def test_start_sets_running(self, event_bus: EventBus) -> None:
        e = RiskEngine(event_bus=event_bus)
        assert e.is_running is False
        await e.start()
        assert e.is_running is True
        await e.stop()

    async def test_stop_clears_running(self, engine: RiskEngine) -> None:
        await engine.stop()
        assert engine.is_running is False

    async def test_start_idempotent(self, engine: RiskEngine) -> None:
        await engine.start()
        assert engine.is_running is True

    async def test_stop_idempotent(self, engine: RiskEngine) -> None:
        await engine.stop()
        await engine.stop()
        assert engine.is_running is False

    async def test_subscribes_to_signals(self, engine: RiskEngine, event_bus: EventBus) -> None:
        assert engine.is_running is True
        assert event_bus.subscriber_count_for(SignalGeneratedEvent) >= 1

    async def test_subscribes_to_fills(self, engine: RiskEngine, event_bus: EventBus) -> None:
        assert engine.is_running is True
        assert event_bus.subscriber_count_for(OrderFilledEvent) >= 1

    async def test_subscribes_to_ticks(self, engine: RiskEngine, event_bus: EventBus) -> None:
        assert engine.is_running is True
        assert event_bus.subscriber_count_for(MarketTickEvent) >= 1

    async def test_subscribes_to_disconnects(self, engine: RiskEngine, event_bus: EventBus) -> None:
        assert engine.is_running is True
        assert event_bus.subscriber_count_for(BrokerDisconnectedEvent) >= 1


class TestRiskEngineKillSwitch:
    async def test_activate_kill_switch(self, engine: RiskEngine) -> None:
        engine.activate_kill_switch()
        assert engine.kill_switch_active is True

    async def test_deactivate_kill_switch(self, engine: RiskEngine) -> None:
        engine.activate_kill_switch()
        engine.deactivate_kill_switch()
        assert engine.kill_switch_active is False

    async def test_kill_switch_rejects_signal(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        engine.activate_kill_switch()

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) >= 1
        assert "kill_switch" in rejected[0].reason

        ordered = [e for e in collected_events if isinstance(e, SignalApprovedEvent)]
        assert len(ordered) == 0


class TestRiskEngineSignalApproval:
    async def test_approves_valid_signal(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
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
        assert approved[0].symbol == "AAPL"
        assert approved[0].side == "BUY"
        assert approved[0].suggested_size == 100

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) == 0

    async def test_rejects_before_start(self, event_bus: EventBus, collected_events: list) -> None:
        RiskEngine(event_bus=event_bus)
        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()
        approved = [e for e in collected_events if isinstance(e, SignalApprovedEvent)]
        assert len(approved) == 0


class TestRiskEngineMaxPositionSize:
    async def test_rejects_excessive_size(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=9999,
                source="test",
            )
        )
        await event_bus.drain()

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) >= 1

        violations = [e for e in collected_events if isinstance(e, RiskViolationEvent)]
        assert len(violations) >= 1
        assert violations[0].rule == "max_position_size"

    async def test_allows_valid_size(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=50,
                source="test",
            )
        )
        await event_bus.drain()

        approved = [e for e in collected_events if isinstance(e, SignalApprovedEvent)]
        assert len(approved) >= 1


class TestRiskEngineDailyLoss:
    async def test_rejects_when_daily_loss_exceeded(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        engine.update_portfolio_state(daily_realized_pnl=-1500.0)

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) >= 1

    async def test_allows_reducing_position_when_over_loss(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        engine.update_portfolio_state(
            daily_realized_pnl=-1500.0,
            positions={"AAPL": 100},
        )

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="SELL",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        approved = [e for e in collected_events if isinstance(e, SignalApprovedEvent)]
        assert len(approved) >= 1
        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) == 0

    async def test_allows_when_within_loss_limit(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        engine.update_portfolio_state(daily_realized_pnl=-500.0)

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
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


class TestRiskEngineMaxLeverage:
    async def test_rejects_when_leverage_exceeded(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        engine.update_portfolio_state(exposure=300_000.0, equity=100_000.0)

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) >= 1

    async def test_allows_when_leverage_within_limit(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        engine.update_portfolio_state(exposure=50_000.0, equity=100_000.0)

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
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

    async def test_no_equity_rejects(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        engine.update_portfolio_state(equity=0.0)

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) >= 1


class TestRiskEngineConcurrentPositions:
    async def test_rejects_when_max_concurrent_reached(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        engine.update_portfolio_state(
            positions={
                "AAPL": 100,
                "MSFT": 50,
                "GOOG": 200,
                "TSLA": 80,
                "AMZN": 60,
                "META": 90,
                "NFLX": 40,
                "NVDA": 150,
                "AMD": 70,
                "INTC": 30,
            },
        )

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="BABA",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) >= 1

    async def test_allows_new_when_under_limit(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        ordered = [e for e in collected_events if isinstance(e, SignalApprovedEvent)]
        assert len(ordered) >= 1


class TestRiskEngineStaleMarket:
    async def test_rejects_when_market_stale(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        engine.update_portfolio_state(
            positions={"AAPL": 0},
        )
        from datetime import UTC, datetime, timedelta

        engine._last_tick_time["AAPL"] = datetime.now(UTC) - timedelta(hours=1)

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) >= 1

    async def test_allows_when_market_fresh(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=150.0, source="test"))
        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        ordered = [e for e in collected_events if isinstance(e, SignalApprovedEvent)]
        assert len(ordered) >= 1


class TestRiskEngineDisconnect:
    async def test_disconnect_activates_kill_switch(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(BrokerDisconnectedEvent(reason="connection_lost", source="test"))
        await event_bus.drain()

        assert engine.kill_switch_active is True
        halted = [e for e in collected_events if isinstance(e, TradingHaltedEvent)]
        assert len(halted) >= 1
        assert "disconnected" in halted[0].reason

    async def test_disconnect_kill_switch_rejects_signals(
        self, engine: RiskEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        await event_bus.publish(BrokerDisconnectedEvent(reason="connection_lost", source="test"))
        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        rejected = [e for e in collected_events if isinstance(e, SignalRejectedEvent)]
        assert len(rejected) >= 1


class TestRiskEngineFillTracking:
    async def test_tracks_position_on_buy_fill(
        self, engine: RiskEngine, event_bus: EventBus
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
        assert engine._positions.get("AAPL") == 100

    async def test_tracks_position_on_sell_fill(
        self, engine: RiskEngine, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderFilledEvent(
                order_id="1",
                symbol="AAPL",
                side="SELL",
                fill_price=150.0,
                fill_quantity=50,
                source="test",
            )
        )
        await event_bus.drain()
        assert engine._positions.get("AAPL") == -50

    async def test_fill_before_start_ignored(self, event_bus: EventBus) -> None:
        e = RiskEngine(event_bus=event_bus)
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
        assert "AAPL" not in e._positions


class TestRiskEngineCustomConfig:
    async def test_custom_max_position_size(self, event_bus: EventBus) -> None:
        e = RiskEngine(event_bus=event_bus, max_position_size=10)
        await e.start()

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=20,
                source="test",
            )
        )
        await event_bus.drain()

        assert e.is_running
        await e.stop()

    async def test_custom_max_daily_loss(self, event_bus: EventBus) -> None:
        e = RiskEngine(event_bus=event_bus, max_daily_loss=100.0)
        await e.start()
        e._daily_realized_pnl = -200.0

        collected: list = []

        async def collector(event: object) -> None:
            collected.append(event)

        event_bus.subscribe_all(collector, name="collector")

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        rejected = [c for c in collected if isinstance(c, SignalRejectedEvent)]
        assert len(rejected) >= 1
        await e.stop()

    async def test_no_stale_market_check_when_no_ticks(self, event_bus: EventBus) -> None:
        e = RiskEngine(event_bus=event_bus, stale_market_seconds=60)
        await e.start()

        collected: list = []

        async def collector(event: object) -> None:
            collected.append(event)

        event_bus.subscribe_all(collector, name="collector")

        await event_bus.publish(
            SignalGeneratedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        ordered = [c for c in collected if isinstance(c, SignalApprovedEvent)]
        assert len(ordered) >= 1
        await e.stop()

    async def test_tick_updates_last_tick_time(
        self, engine: RiskEngine, event_bus: EventBus
    ) -> None:
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=150.0, source="test"))
        await event_bus.drain()
        assert "AAPL" in engine._last_tick_time

    async def test_reset_daily_pnl(self, engine: RiskEngine) -> None:
        engine._daily_realized_pnl = -500.0
        engine.reset_daily_pnl()
        assert engine.daily_realized_pnl == 0.0


class TestRiskEngineExposureUpdate:
    async def test_subscribes_to_exposure_updates(
        self, engine: RiskEngine, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        assert event_bus.subscriber_count_for(ExposureUpdatedEvent) >= 1

    async def test_auto_updates_exposure_and_equity(
        self, engine: RiskEngine, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=50_000.0,
                net_exposure=30_000.0,
                leverage=0.5,
                long_count=1,
                short_count=0,
                equity=100_000.0,
                source="test",
            )
        )
        await event_bus.drain()
        assert engine._exposure == 50_000.0
        assert engine._equity == 100_000.0

    async def test_auto_update_before_start_ignored(self, event_bus: EventBus) -> None:
        e = RiskEngine(event_bus=event_bus)
        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=50_000.0,
                net_exposure=30_000.0,
                leverage=0.5,
                long_count=1,
                short_count=0,
                equity=100_000.0,
                source="test",
            )
        )
        await event_bus.drain()
        assert e._exposure == 0.0
        assert e._equity == 100_000.0
