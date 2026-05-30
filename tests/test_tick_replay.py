from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    MarketTickEvent,
    SignalGeneratedEvent,
)
from edrader.replay.clock import ReplayClock
from edrader.replay.engine import ReplayEngine
from edrader.replay.historical_feed import HistoricalFeed
from edrader.strategies.examples.vwap_reversion import VwapReversionStrategy


class TestLoadTickCsv:
    def test_load_tick_csv_generates_market_tick_events(self, tmp_path) -> None:
        csv_path = tmp_path / "ticks.csv"
        csv_path.write_text(
            "time,price,volume,bid,ask\n"
            "2024-01-01T09:30:00,150.5,100,150.4,150.6\n"
            "2024-01-01T09:30:01,150.6,200,150.5,150.7\n"
        )

        feed = HistoricalFeed()
        events = feed.load_tick_csv(str(csv_path), symbol="AAPL")

        assert len(events) == 2
        assert all(isinstance(e, MarketTickEvent) for e in events)
        assert events[0].symbol == "AAPL"
        assert events[0].price == 150.5
        assert events[0].volume == 100
        assert events[0].bid == 150.4
        assert events[0].ask == 150.6

    def test_load_tick_csv_minimal_columns(self, tmp_path) -> None:
        csv_path = tmp_path / "ticks.csv"
        csv_path.write_text("time,price,volume\n" "2024-01-01T09:30:00,150.5,100\n")

        feed = HistoricalFeed()
        events = feed.load_tick_csv(str(csv_path), symbol="AAPL")

        assert len(events) == 1
        assert events[0].price == 150.5
        assert events[0].volume == 100
        assert events[0].bid == 0.0
        assert events[0].ask == 0.0

    def test_load_tick_csv_sorts_by_timestamp(self, tmp_path) -> None:
        csv_path = tmp_path / "ticks.csv"
        csv_path.write_text(
            "time,price,volume\n"
            "2024-01-01T09:30:01,151.0,200\n"
            "2024-01-01T09:30:00,150.5,100\n"
        )

        feed = HistoricalFeed()
        events = feed.load_tick_csv(str(csv_path), symbol="AAPL")

        assert len(events) == 2
        assert events[0].price == 150.5
        assert events[1].price == 151.0

    def test_load_tick_csv_filter_by_date(self, tmp_path) -> None:
        csv_path = tmp_path / "ticks.csv"
        csv_path.write_text(
            "time,price,volume\n"
            "2024-01-01T09:30:00,150.5,100\n"
            "2024-01-02T09:30:00,151.5,200\n"
        )

        feed = HistoricalFeed()
        start = datetime(2024, 1, 2, tzinfo=UTC)
        events = feed.load_tick_csv(str(csv_path), symbol="AAPL", start=start)

        assert len(events) == 1
        assert events[0].price == 151.5

    def test_load_tick_csv_custom_columns(self, tmp_path) -> None:
        csv_path = tmp_path / "ticks.csv"
        csv_path.write_text("ts,p,v\n" "2024-01-01T09:30:00,150.5,100\n")

        feed = HistoricalFeed()
        events = feed.load_tick_csv(
            str(csv_path), symbol="AAPL", time_column="ts", price_column="p", volume_column="v"
        )

        assert len(events) == 1
        assert events[0].price == 150.5
        assert events[0].volume == 100

    def test_events_property_holds_both_bar_and_tick(self, tmp_path) -> None:
        csv_path = tmp_path / "ticks.csv"
        csv_path.write_text("time,price,volume\n2024-01-01T09:30:00,150.5,100\n")

        feed = HistoricalFeed()
        feed.load_tick_csv(str(csv_path), symbol="AAPL")
        all_events = feed.events

        assert len(all_events) == 1
        assert isinstance(all_events[0], MarketTickEvent)


class TestVwapReversionStrategy:
    async def test_initial_properties(self) -> None:
        event_bus = EventBus()
        s = VwapReversionStrategy("vwap-1", event_bus, window=50, entry_pct=0.01, exit_pct=0.002)
        assert s.strategy_id == "vwap-1"
        assert s.window == 50
        assert s.is_running is False

    async def test_event_types(self) -> None:
        event_bus = EventBus()
        s = VwapReversionStrategy("vwap-1", event_bus)
        assert MarketTickEvent in s.event_types()

    async def test_ignores_non_tick_events(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = VwapReversionStrategy("vwap-1", event_bus, window=10, entry_pct=0.01)
        await s.start()

        from edrader.events.event_types import BarCloseEvent

        await event_bus.publish(BarCloseEvent(symbol="AAPL", close=150.0, source="test"))
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        assert len(signals) == 0
        await s.stop()

    async def test_no_signal_before_warmup(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = VwapReversionStrategy("vwap-1", event_bus, window=20, entry_pct=0.01)
        await s.start()

        for _ in range(10):
            await event_bus.publish(
                MarketTickEvent(symbol="AAPL", price=100.0, volume=100, source="test")
            )
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        assert len(signals) == 0
        await s.stop()

    async def test_sell_signal_when_price_above_vwap(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = VwapReversionStrategy("vwap-1", event_bus, window=20, entry_pct=0.01)
        await s.start()

        for _ in range(20):
            await event_bus.publish(
                MarketTickEvent(symbol="AAPL", price=100.0, volume=100, source="test")
            )

        await event_bus.publish(
            MarketTickEvent(symbol="AAPL", price=102.0, volume=100, source="test")
        )
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        sell_signals = [s for s in signals if s.side == "SELL"]
        assert len(sell_signals) >= 1
        await s.stop()

    async def test_buy_signal_when_price_below_vwap(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = VwapReversionStrategy("vwap-1", event_bus, window=20, entry_pct=0.01)
        await s.start()

        for _ in range(20):
            await event_bus.publish(
                MarketTickEvent(symbol="AAPL", price=100.0, volume=100, source="test")
            )

        await event_bus.publish(
            MarketTickEvent(symbol="AAPL", price=98.0, volume=100, source="test")
        )
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        buy_signals = [s for s in signals if s.side == "BUY"]
        assert len(buy_signals) >= 1
        await s.stop()

    async def test_exit_signal_when_price_reverts(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = VwapReversionStrategy("vwap-1", event_bus, window=20, entry_pct=0.01, exit_pct=0.002)
        await s.start()

        for _ in range(20):
            await event_bus.publish(
                MarketTickEvent(symbol="AAPL", price=100.0, volume=100, source="test")
            )

        await event_bus.publish(
            MarketTickEvent(symbol="AAPL", price=102.0, volume=100, source="test")
        )

        await event_bus.publish(
            MarketTickEvent(symbol="AAPL", price=100.2, volume=100, source="test")
        )
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        sides = [s.side for s in signals]
        assert "SELL" in sides
        assert "BUY" in sides
        assert sides[-1] == "BUY"
        await s.stop()

    async def test_ignores_zero_volume_ticks(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        s = VwapReversionStrategy("vwap-1", event_bus, window=10, entry_pct=0.01)
        await s.start()

        for _ in range(20):
            await event_bus.publish(
                MarketTickEvent(symbol="AAPL", price=100.0, volume=100, source="test")
            )

        await event_bus.publish(
            MarketTickEvent(symbol="AAPL", price=102.0, volume=0, source="test")
        )
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        sell_signals = [s for s in signals if s.side == "SELL"]
        assert len(sell_signals) == 0
        await s.stop()

    async def test_tick_replay_integration(
        self, event_bus: EventBus, collected_events: list, tmp_path
    ) -> None:
        csv_path = tmp_path / "ticks.csv"
        lines = ["time,price,volume\n"]
        base = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
        for i in range(30):
            ts = base + timedelta(seconds=i)
            lines.append(f"{ts.isoformat()},100.0,100\n")
        lines.append(f"{(base + timedelta(seconds=30)).isoformat()},102.0,100\n")
        csv_path.write_text("".join(lines))

        s = VwapReversionStrategy("vwap-1", event_bus, window=20, entry_pct=0.01)
        await s.start()

        feed = HistoricalFeed()
        feed.load_tick_csv(str(csv_path), symbol="AAPL")

        clock = ReplayClock()
        clock.speed = 1_000_000
        engine = ReplayEngine(event_bus, clock=clock)
        engine.load_events(feed.events)

        await engine.run()
        await event_bus.drain()

        signals = [e for e in collected_events if isinstance(e, SignalGeneratedEvent)]
        sell_signals = [s for s in signals if s.side == "SELL"]
        assert len(sell_signals) >= 1

        await s.stop()


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
