from __future__ import annotations

import pytest

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BarCloseEvent,
    BaseEvent,
    SignalGeneratedEvent,
)
from trading_platform.strategies.base import Strategy, StrategyLoader


class BlankStrategy(Strategy):
    def __init__(self, strategy_id: str, event_bus: EventBus) -> None:
        super().__init__(strategy_id, event_bus)
        self.received_events: list[BaseEvent] = []

    async def on_event(self, event: BaseEvent) -> None:
        self.received_events.append(event)


class FilterStrategy(Strategy):
    def __init__(self, strategy_id: str, event_bus: EventBus) -> None:
        super().__init__(strategy_id, event_bus)
        self.received: list[BaseEvent] = []

    def event_types(self) -> list[type[BaseEvent]]:
        from trading_platform.events.event_types import BarCloseEvent, MarketTickEvent

        return [BarCloseEvent, MarketTickEvent]

    async def on_event(self, event: BaseEvent) -> None:
        self.received.append(event)


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


class TestStrategyLifecycle:
    async def test_initial_state(self, event_bus: EventBus) -> None:
        s = BlankStrategy("test-1", event_bus)
        assert s.strategy_id == "test-1"
        assert s.is_running is False

    async def test_start_sets_running(self, event_bus: EventBus) -> None:
        s = BlankStrategy("test-1", event_bus)
        await s.start()
        assert s.is_running is True

    async def test_stop_clears_running(self, event_bus: EventBus) -> None:
        s = BlankStrategy("test-1", event_bus)
        await s.start()
        await s.stop()
        assert s.is_running is False

    async def test_start_idempotent(self, event_bus: EventBus) -> None:
        s = BlankStrategy("test-1", event_bus)
        await s.start()
        await s.start()
        assert s.is_running is True

    async def test_stop_idempotent(self, event_bus: EventBus) -> None:
        s = BlankStrategy("test-1", event_bus)
        await s.start()
        await s.stop()
        await s.stop()
        assert s.is_running is False

    async def test_on_start_called(self, event_bus: EventBus) -> None:
        called = False

        class CustomStrategy(Strategy):
            async def on_event(self, event: BaseEvent) -> None:
                pass

            async def on_start(self) -> None:
                nonlocal called
                called = True

        s = CustomStrategy("test-1", event_bus)
        await s.start()
        assert called is True

    async def test_on_stop_called(self, event_bus: EventBus) -> None:
        called = False

        class CustomStrategy(Strategy):
            async def on_event(self, event: BaseEvent) -> None:
                pass

            async def on_stop(self) -> None:
                nonlocal called
                called = True

        s = CustomStrategy("test-1", event_bus)
        await s.start()
        await s.stop()
        assert called is True


class TestStrategyEventSubscription:
    async def test_subscribes_to_bar_close_by_default(self, event_bus: EventBus) -> None:
        s = BlankStrategy("test-1", event_bus)
        await s.start()
        assert event_bus.subscriber_count_for(BarCloseEvent) >= 1

    async def test_receives_subscribed_events(self, event_bus: EventBus) -> None:
        s = BlankStrategy("test-1", event_bus)
        await s.start()

        await event_bus.publish(BarCloseEvent(symbol="AAPL", close=150.0, source="test"))
        await event_bus.drain()

        assert len(s.received_events) >= 1
        received_bar = [e for e in s.received_events if isinstance(e, BarCloseEvent)]
        assert len(received_bar) >= 1
        assert received_bar[0].symbol == "AAPL"

    async def test_stop_unsubscribes(self, event_bus: EventBus) -> None:
        s = BlankStrategy("test-1", event_bus)
        await s.start()
        initial_count = event_bus.subscriber_count_for(BarCloseEvent)
        assert initial_count >= 1

        await s.stop()
        after_stop_count = event_bus.subscriber_count_for(BarCloseEvent)
        assert after_stop_count < initial_count

    async def test_custom_event_types(self, event_bus: EventBus) -> None:
        from trading_platform.events.event_types import MarketTickEvent

        s = FilterStrategy("test-filter", event_bus)
        await s.start()

        await event_bus.publish(MarketTickEvent(symbol="AAPL", price=150.0, source="test"))
        await event_bus.drain()

        assert len(s.received) >= 1
        assert s.received[0].symbol == "AAPL"


class TestStrategySignalEmission:
    async def test_emit_signal_publishes_event(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = BlankStrategy("test-signal", event_bus)
        await s.start()

        await s.emit_signal("AAPL", "BUY", 0.8, 100)
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        assert len(signals) >= 1
        assert signals[0].strategy_id == "test-signal"
        assert signals[0].symbol == "AAPL"
        assert signals[0].side == "BUY"
        assert signals[0].confidence == 0.8
        assert signals[0].suggested_size == 100

    async def test_emit_signal_before_start_ignored(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = BlankStrategy("test-signal", event_bus)

        await s.emit_signal("AAPL", "BUY", 0.8, 100)
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        assert len(signals) == 0


class TestStrategyLoader:
    def test_register_and_create(self, event_bus: EventBus) -> None:
        loader = StrategyLoader()
        loader.register("blank", BlankStrategy)
        assert "blank" in loader.registered_ids

        s = loader.create("blank", event_bus)
        assert isinstance(s, BlankStrategy)
        assert s.strategy_id == "blank"

    def test_register_duplicate_raises(self) -> None:
        loader = StrategyLoader()
        loader.register("dup", BlankStrategy)
        with pytest.raises(ValueError, match="already registered"):
            loader.register("dup", BlankStrategy)

    def test_create_unknown_raises(self, event_bus: EventBus) -> None:
        loader = StrategyLoader()
        with pytest.raises(KeyError, match="unknown"):
            loader.create("unknown", event_bus)

    def test_initial_registry_empty(self) -> None:
        loader = StrategyLoader()
        assert loader.registered_ids == []

    async def test_create_and_run_strategy(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        loader = StrategyLoader()
        loader.register("blank", BlankStrategy)
        s = loader.create("blank", event_bus)

        await s.start()
        await s.emit_signal("AAPL", "BUY", 0.8, 100)
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        assert len(signals) >= 1
        await s.stop()
