from __future__ import annotations

import pytest

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    ExposureUpdatedEvent,
    MarketTickEvent,
    OrderRequestedEvent,
    OrderSubmittedEvent,
    SignalApprovedEvent,
)
from edrader.execution.engine import ExecutionEngine
from edrader.execution.sizing import SizingEngine


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
async def engine(event_bus: EventBus) -> ExecutionEngine:
    e = ExecutionEngine(event_bus=event_bus)
    await e.start()
    yield e
    await e.stop()


class TestExecutionEngineLifecycle:
    async def test_initial_state(self, engine: ExecutionEngine) -> None:
        assert engine.is_running is True
        assert engine.active_order_count == 0

    async def test_start_sets_running(self, event_bus: EventBus) -> None:
        e = ExecutionEngine(event_bus=event_bus)
        assert e.is_running is False
        await e.start()
        assert e.is_running is True
        await e.stop()

    async def test_stop_clears_running(self, engine: ExecutionEngine) -> None:
        await engine.stop()
        assert engine.is_running is False

    async def test_start_idempotent(self, engine: ExecutionEngine) -> None:
        await engine.start()
        assert engine.is_running is True

    async def test_stop_idempotent(self, engine: ExecutionEngine) -> None:
        await engine.stop()
        await engine.stop()
        assert engine.is_running is False

    async def test_subscribes_to_approved_signals(
        self, engine: ExecutionEngine, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        assert event_bus.subscriber_count_for(SignalApprovedEvent) >= 1

    async def test_subscribes_to_ticks(self, engine: ExecutionEngine, event_bus: EventBus) -> None:
        assert engine.is_running is True
        assert event_bus.subscriber_count_for(MarketTickEvent) >= 1

    async def test_subscribes_to_submitted(
        self, engine: ExecutionEngine, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        assert event_bus.subscriber_count_for(OrderSubmittedEvent) >= 1

    async def test_subscribes_to_exposure_updates(
        self, engine: ExecutionEngine, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        assert event_bus.subscriber_count_for(ExposureUpdatedEvent) >= 1


class TestExecutionEngineSignalProcessing:
    async def test_approved_signal_creates_order_request(
        self, engine: ExecutionEngine, collected_events: list, event_bus: EventBus
    ) -> None:
        assert engine.is_running is True
        await event_bus.publish(
            SignalApprovedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        orders = [e for e in collected_events if isinstance(e, OrderRequestedEvent)]
        assert len(orders) >= 1
        assert orders[0].symbol == "AAPL"
        assert orders[0].side == "BUY"
        assert orders[0].quantity == 100
        assert orders[0].order_type == "MKT"

    async def test_approved_signal_before_start_ignored(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        ExecutionEngine(event_bus=event_bus)
        await event_bus.publish(
            SignalApprovedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        orders = [e for e in collected_events if isinstance(e, OrderRequestedEvent)]
        assert len(orders) == 0

    async def test_tick_updates_price_cache(
        self, engine: ExecutionEngine, event_bus: EventBus
    ) -> None:
        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=150.0, source="test"))
        await event_bus.drain()
        assert engine._prices.get("AAPL") == 150.0

    async def test_submitted_event_tracks_active_order(
        self, engine: ExecutionEngine, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderSubmittedEvent(
                order_id="123",
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()
        assert engine.active_order_count == 1
        assert "123" in engine.active_orders
        assert engine.active_orders["123"]["symbol"] == "AAPL"

    async def test_submitted_without_order_id_ignored(
        self, engine: ExecutionEngine, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderSubmittedEvent(
                order_id="",
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()
        assert engine.active_order_count == 0

    async def test_exposure_update_tracks_equity(
        self, engine: ExecutionEngine, event_bus: EventBus
    ) -> None:
        await event_bus.publish(ExposureUpdatedEvent(equity=50_000.0, source="test"))
        await event_bus.drain()
        assert engine._equity == 50_000.0


class TestExecutionEngineThrottle:
    async def test_throttle_blocks_rapid_orders(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        e = ExecutionEngine(event_bus=event_bus, throttle_delay=10.0)
        await e.start()

        await event_bus.publish(
            SignalApprovedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        orders = [ev for ev in collected_events if isinstance(ev, OrderRequestedEvent)]
        assert len(orders) == 1

        await event_bus.publish(
            SignalApprovedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.drain()

        orders = [ev for ev in collected_events if isinstance(ev, OrderRequestedEvent)]
        assert len(orders) == 1
        await e.stop()

    async def test_no_throttle_when_delay_zero(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        e = ExecutionEngine(event_bus=event_bus, throttle_delay=0.0)
        await e.start()

        for _ in range(3):
            await event_bus.publish(
                SignalApprovedEvent(
                    strategy_id="test",
                    symbol="AAPL",
                    side="BUY",
                    confidence=0.8,
                    suggested_size=100,
                    source="test",
                )
            )
        await event_bus.drain()

        orders = [ev for ev in collected_events if isinstance(ev, OrderRequestedEvent)]
        assert len(orders) == 3
        await e.stop()

    async def test_throttle_per_symbol_independent(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        e = ExecutionEngine(event_bus=event_bus, throttle_delay=10.0)
        await e.start()

        await event_bus.publish(
            SignalApprovedEvent(
                strategy_id="test",
                symbol="AAPL",
                side="BUY",
                confidence=0.8,
                suggested_size=100,
                source="test",
            )
        )
        await event_bus.publish(
            SignalApprovedEvent(
                strategy_id="test",
                symbol="MSFT",
                side="BUY",
                confidence=0.8,
                suggested_size=50,
                source="test",
            )
        )
        await event_bus.drain()

        orders = [ev for ev in collected_events if isinstance(ev, OrderRequestedEvent)]
        assert len(orders) == 2
        await e.stop()


class TestSizingEngine:
    def test_fixed_sizing_default(self) -> None:
        s = SizingEngine()
        size = s.compute_size(suggested_size=100)
        assert size == 100

    def test_fixed_sizing_explicit_method(self) -> None:
        s = SizingEngine(method="fixed")
        size = s.compute_size(suggested_size=50)
        assert size == 50

    def test_percent_equity_with_price_and_equity(self) -> None:
        s = SizingEngine(method="percent_equity", percent_equity_fraction=0.02)
        size = s.compute_size(suggested_size=100, price=200.0, equity=100_000.0)
        expected = int(100_000.0 * 0.02 / 200.0)
        assert size == max(1, expected)

    def test_percent_equity_no_equity_falls_back(self) -> None:
        s = SizingEngine(method="percent_equity")
        size = s.compute_size(suggested_size=100)
        assert size == 100

    def test_percent_equity_no_price_falls_back(self) -> None:
        s = SizingEngine(method="percent_equity")
        size = s.compute_size(suggested_size=100, equity=100_000.0)
        assert size == 100

    def test_percent_equity_zero_price_falls_back(self) -> None:
        s = SizingEngine(method="percent_equity")
        size = s.compute_size(suggested_size=100, price=0.0, equity=100_000.0)
        assert size == 100

    def test_percent_equity_zero_equity_falls_back(self) -> None:
        s = SizingEngine(method="percent_equity")
        size = s.compute_size(suggested_size=100, price=200.0, equity=0.0)
        assert size == 100

    def test_minimum_size_of_one(self) -> None:
        s = SizingEngine(method="percent_equity", percent_equity_fraction=0.01)
        size = s.compute_size(suggested_size=100, price=1_000_000.0, equity=1_000.0)
        assert size >= 1

    def test_volatility_sizing_falls_back_to_suggested(self) -> None:
        s = SizingEngine(method="volatility")
        size = s.compute_size(suggested_size=100, price=200.0)
        assert size == 100

    def test_method_property(self) -> None:
        s = SizingEngine(method="percent_equity")
        assert s.method == "percent_equity"

    def test_update_atr(self) -> None:
        s = SizingEngine()
        s.update_atr("AAPL", 2.5)
        assert s._atr_cache["AAPL"] == 2.5

    def test_compute_size_with_override_method(self) -> None:
        s = SizingEngine(method="fixed")
        size = s.compute_size(
            suggested_size=75, method="percent_equity", price=100.0, equity=50_000.0
        )
        expected = int(50_000.0 * 0.02 / 100.0)
        assert size == max(1, expected)
