from __future__ import annotations

import pytest

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BarCloseEvent,
    SignalGeneratedEvent,
)
from trading_platform.strategies.examples.mean_reversion import MeanReversionStrategy
from trading_platform.strategies.examples.sma_crossover import SmaCrossoverStrategy


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


class TestSmaCrossoverStrategy:
    async def test_initial_properties(self) -> None:
        event_bus = EventBus()
        s = SmaCrossoverStrategy("sma-1", event_bus, fast_window=5, slow_window=15)
        assert s.strategy_id == "sma-1"
        assert s.fast_window == 5
        assert s.slow_window == 15
        assert s.is_running is False

    async def test_no_signal_before_warmup(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = SmaCrossoverStrategy("sma-1", event_bus, fast_window=3, slow_window=5)
        await s.start()

        for i in range(4):
            await event_bus.publish(
                BarCloseEvent(symbol="AAPL", close=float(100 + i), source="test")
            )
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        assert len(signals) == 0
        await s.stop()

    async def test_buy_signal_on_crossover_up(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = SmaCrossoverStrategy("sma-1", event_bus, fast_window=3, slow_window=5)
        await s.start()

        for close in [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]:
            await event_bus.publish(BarCloseEvent(symbol="AAPL", close=float(close), source="test"))
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        assert len(signals) >= 1
        assert signals[0].symbol == "AAPL"
        assert signals[0].side == "BUY"
        await s.stop()

    async def test_sell_signal_on_crossover_down(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = SmaCrossoverStrategy("sma-1", event_bus, fast_window=3, slow_window=5)
        await s.start()

        for close in [110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100]:
            await event_bus.publish(BarCloseEvent(symbol="AAPL", close=float(close), source="test"))
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        assert len(signals) >= 1
        sell_signals = [s for s in signals if s.side == "SELL"]
        assert len(sell_signals) >= 1
        await s.stop()

    async def test_multiple_symbols_independent(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = SmaCrossoverStrategy("sma-1", event_bus, fast_window=2, slow_window=3)
        await s.start()

        for close in [100, 101, 102]:
            await event_bus.publish(BarCloseEvent(symbol="AAPL", close=float(close), source="test"))
        for close in [200, 201, 202]:
            await event_bus.publish(BarCloseEvent(symbol="MSFT", close=float(close), source="test"))
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        aapl_signals = [s for s in signals if s.symbol == "AAPL"]
        msft_signals = [s for s in signals if s.symbol == "MSFT"]
        assert len(aapl_signals) >= 1
        assert len(msft_signals) >= 1
        await s.stop()


class TestMeanReversionStrategy:
    async def test_initial_properties(self) -> None:
        event_bus = EventBus()
        s = MeanReversionStrategy("mr-1", event_bus, window=15, entry_z=1.5, exit_z=0.5)
        assert s.strategy_id == "mr-1"
        assert s.window == 15
        assert s.entry_z == 1.5
        assert s.exit_z == 0.5

    async def test_no_signal_before_warmup(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = MeanReversionStrategy("mr-1", event_bus, window=10, entry_z=1.5, exit_z=0.5)
        await s.start()

        for _ in range(5):
            await event_bus.publish(BarCloseEvent(symbol="AAPL", close=100.0, source="test"))
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        assert len(signals) == 0
        await s.stop()

    async def test_buy_signal_on_low_price(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = MeanReversionStrategy("mr-1", event_bus, window=5, entry_z=1.5, exit_z=0.5)
        await s.start()

        for _ in range(5):
            await event_bus.publish(BarCloseEvent(symbol="AAPL", close=100.0, source="test"))

        await event_bus.publish(BarCloseEvent(symbol="AAPL", close=90.0, source="test"))
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        buy_signals = [s for s in signals if s.side == "BUY"]
        assert len(buy_signals) >= 1
        assert buy_signals[0].symbol == "AAPL"
        await s.stop()

    async def test_sell_signal_on_high_price(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = MeanReversionStrategy("mr-1", event_bus, window=5, entry_z=1.5, exit_z=0.5)
        await s.start()

        for _ in range(5):
            await event_bus.publish(BarCloseEvent(symbol="AAPL", close=100.0, source="test"))

        await event_bus.publish(BarCloseEvent(symbol="AAPL", close=110.0, source="test"))
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        sell_signals = [s for s in signals if s.side == "SELL"]
        assert len(sell_signals) >= 1
        assert sell_signals[0].symbol == "AAPL"
        await s.stop()

    async def test_exit_signal_after_entry(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = MeanReversionStrategy("mr-1", event_bus, window=5, entry_z=1.5, exit_z=0.5)
        await s.start()

        for _ in range(5):
            await event_bus.publish(BarCloseEvent(symbol="AAPL", close=100.0, source="test"))

        await event_bus.publish(BarCloseEvent(symbol="AAPL", close=90.0, source="test"))

        await event_bus.publish(BarCloseEvent(symbol="AAPL", close=95.0, source="test"))
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        buy_signals = [s for s in signals if s.side == "BUY"]
        sell_signals = [s for s in signals if s.side == "SELL"]
        assert len(buy_signals) >= 1
        assert len(sell_signals) >= 1
        await s.stop()
