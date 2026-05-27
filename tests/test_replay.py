from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from edrader.events.bus import EventBus
from edrader.events.event_types import BarCloseEvent, BaseEvent
from edrader.replay.clock import ReplayClock
from edrader.replay.engine import ReplayEngine
from edrader.replay.historical_feed import HistoricalFeed


class TestHistoricalFeed:
    def test_load_csv_generates_events(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "time,open,high,low,close,volume\n"
            "2024-01-01T09:30:00,150.0,151.0,149.5,150.5,10000\n"
            "2024-01-01T09:31:00,150.5,152.0,150.0,151.5,12000\n"
        )

        feed = HistoricalFeed()
        events = feed.load_csv(str(csv_path), symbol="AAPL")

        assert len(events) == 2
        assert all(isinstance(e, BarCloseEvent) for e in events)
        assert events[0].symbol == "AAPL"
        assert events[0].open == 150.0
        assert events[0].close == 150.5
        assert events[1].close == 151.5

    def test_load_csv_sorts_by_timestamp(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "time,open,high,low,close,volume\n"
            "2024-01-01T09:31:00,151.0,152.0,150.0,151.5,100\n"
            "2024-01-01T09:30:00,150.0,151.0,149.5,150.5,100\n"
        )

        feed = HistoricalFeed()
        events = feed.load_csv(str(csv_path), symbol="AAPL")

        assert events[0].close == 150.5
        assert events[1].close == 151.5

    def test_load_csv_filter_by_date(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "time,open,high,low,close,volume\n"
            "2024-01-01T09:30:00,150.0,151.0,149.5,150.5,100\n"
            "2024-01-02T09:30:00,151.0,152.0,150.5,151.5,100\n"
        )

        feed = HistoricalFeed()
        start = datetime(2024, 1, 2, tzinfo=UTC)
        events = feed.load_csv(str(csv_path), symbol="AAPL", start=start)

        assert len(events) == 1
        assert events[0].close == 151.5

    def test_load_csv_column_mapping(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("ts,o,h,l,c,v\n" "2024-01-01T09:30:00,150.0,151.0,149.5,150.5,10000\n")

        feed = HistoricalFeed()
        events = feed.load_csv(
            str(csv_path),
            symbol="AAPL",
            time_column="ts",
            open_column="o",
            high_column="h",
            low_column="l",
            close_column="c",
            volume_column="v",
        )

        assert len(events) == 1
        assert events[0].open == 150.0
        assert events[0].volume == 10000

    def test_load_csv_missing_file(self) -> None:
        feed = HistoricalFeed()
        with pytest.raises(FileNotFoundError):
            feed.load_csv("/nonexistent/file.csv", symbol="AAPL")

    def test_load_csv_malformed_row_skipped(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "time,open,high,low,close,volume\n"
            "2024-01-01T09:30:00,150.0,151.0,149.5,150.5,10000\n"
            "bad_data\n"
        )

        feed = HistoricalFeed()
        events = feed.load_csv(str(csv_path), symbol="AAPL")
        assert len(events) == 1

    def test_load_csv_empty_file(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("time,open,high,low,close,volume\n")

        feed = HistoricalFeed()
        events = feed.load_csv(str(csv_path), symbol="AAPL")
        assert len(events) == 0

    def test_filter_by_date(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "time,open,high,low,close,volume\n"
            "2024-01-01T09:30:00,150.0,151.0,149.5,150.5,100\n"
            "2024-01-02T09:30:00,151.0,152.0,150.5,151.5,100\n"
        )

        feed = HistoricalFeed()
        feed.load_csv(str(csv_path), symbol="AAPL")

        filtered = feed.filter_by_date(
            start=datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert len(filtered) == 1

    def test_clear(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "time,open,high,low,close,volume\n" "2024-01-01T09:30:00,150.0,151.0,149.5,150.5,100\n"
        )

        feed = HistoricalFeed()
        feed.load_csv(str(csv_path), symbol="AAPL")
        assert feed.event_count == 1
        feed.clear()
        assert feed.event_count == 0

    def test_events_property_returns_copy(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "time,open,high,low,close,volume\n" "2024-01-01T09:30:00,150.0,151.0,149.5,150.5,100\n"
        )

        feed = HistoricalFeed()
        feed.load_csv(str(csv_path), symbol="AAPL")
        evts = feed.events
        evts.clear()
        assert feed.event_count == 1

    def test_custom_date_format(self, tmp_path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "time,open,high,low,close,volume\n" "01/01/2024 09:30,150.0,151.0,149.5,150.5,100\n"
        )

        feed = HistoricalFeed()
        events = feed.load_csv(str(csv_path), symbol="AAPL", date_format="%m/%d/%Y %H:%M")
        assert len(events) == 1


class TestReplayClock:
    def test_initial_state(self) -> None:
        clock = ReplayClock()
        assert clock.speed == 1.0
        assert clock.is_paused is False

    def test_speed_setter(self) -> None:
        clock = ReplayClock()
        clock.speed = 10.0
        assert clock.speed == 10.0

    def test_speed_must_be_positive(self) -> None:
        clock = ReplayClock()
        with pytest.raises(ValueError):
            clock.speed = 0

    def test_now_advances_with_speed(self) -> None:
        base = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
        clock = ReplayClock(start_time=base)
        clock.speed = 2.0
        clock.advance(60)
        result = clock.now()
        expected = base + timedelta(seconds=120)
        assert result == expected

    def test_pause_stops_time(self) -> None:
        base = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
        clock = ReplayClock(start_time=base)
        clock.pause()
        clock.advance(60)
        assert clock.now() == base

    def test_resume_after_pause(self) -> None:
        base = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
        clock = ReplayClock(start_time=base)
        clock.pause()
        clock.advance(60)
        clock.resume()
        assert clock.is_paused is False
        clock.advance(10)
        assert clock.now() > base

    def test_reset(self) -> None:
        base = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
        clock = ReplayClock(start_time=base)
        clock.speed = 5.0
        clock.pause()
        clock.reset()
        assert clock.speed == 1.0
        assert clock.is_paused is False

    def test_set_time(self) -> None:
        base = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
        clock = ReplayClock(start_time=base)
        new_time = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)
        clock.set_time(new_time)
        assert clock.now() == new_time
        assert clock.base_time == new_time


class TestReplayEngine:
    @pytest.fixture
    async def event_bus(self) -> EventBus:
        bus = EventBus()
        await bus.start()
        yield bus
        await bus.stop()

    @pytest.fixture
    def events(self) -> list[BarCloseEvent]:
        base = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
        return [
            BarCloseEvent(
                symbol="AAPL",
                open=150,
                high=151,
                low=149,
                close=150.5,
                volume=1000,
                timestamp=base,
            ),
            BarCloseEvent(
                symbol="AAPL",
                open=150.5,
                high=152,
                low=150,
                close=151,
                volume=1200,
                timestamp=base + timedelta(minutes=1),
            ),
            BarCloseEvent(
                symbol="AAPL",
                open=151,
                high=153,
                low=150.5,
                close=152,
                volume=1400,
                timestamp=base + timedelta(minutes=2),
            ),
        ]

    async def test_initial_state(self, event_bus: EventBus) -> None:
        engine = ReplayEngine(event_bus=event_bus)
        assert engine.is_running is False
        assert engine.is_paused is False
        assert engine.total_events == 0
        assert engine.current_index == 0

    async def test_load_events(self, event_bus: EventBus, events: list[BarCloseEvent]) -> None:
        engine = ReplayEngine(event_bus=event_bus)
        engine.load_events(events)
        assert engine.total_events == 3
        assert engine.current_index == 0

    async def test_load_events_sets_clock(
        self, event_bus: EventBus, events: list[BarCloseEvent]
    ) -> None:
        engine = ReplayEngine(event_bus=event_bus)
        engine.load_events(events)
        assert engine.clock.base_time == events[0].timestamp

    async def test_step_publishes_event(
        self, event_bus: EventBus, events: list[BarCloseEvent]
    ) -> None:
        collected: list[BaseEvent] = []

        async def collector(event: BaseEvent) -> None:
            collected.append(event)

        event_bus.subscribe_all(collector, name="collector")

        engine = ReplayEngine(event_bus=event_bus)
        engine.load_events(events)

        result = await engine.step()
        await event_bus.drain()

        assert result is True
        assert len(collected) >= 1
        assert collected[0].symbol == "AAPL"
        assert engine.current_index == 1

    async def test_step_returns_false_when_done(
        self, event_bus: EventBus, events: list[BarCloseEvent]
    ) -> None:
        engine = ReplayEngine(event_bus=event_bus)
        engine.load_events(events)

        for _ in range(3):
            await engine.step()

        result = await engine.step()
        assert result is False

    async def test_run_publishes_all_events(
        self, event_bus: EventBus, events: list[BarCloseEvent]
    ) -> None:
        collected: list[BaseEvent] = []

        async def collector(event: BaseEvent) -> None:
            collected.append(event)

        event_bus.subscribe_all(collector, name="collector")

        engine = ReplayEngine(event_bus=event_bus)
        engine.clock.speed = 1000
        engine.load_events(events)
        await engine.run()
        await event_bus.drain()

        bar_events = [e for e in collected if isinstance(e, BarCloseEvent)]
        assert len(bar_events) == 3

    async def test_pause_and_resume(self, event_bus: EventBus, events: list[BarCloseEvent]) -> None:
        engine = ReplayEngine(event_bus=event_bus)
        engine.clock.speed = 1000
        engine.load_events(events)

        engine.pause()
        assert engine.is_paused is True
        assert engine.clock.is_paused is True

        engine.resume()
        assert engine.is_paused is False
        assert engine.clock.is_paused is False

    async def test_stop_during_run(self, event_bus: EventBus, events: list[BarCloseEvent]) -> None:
        engine = ReplayEngine(event_bus=event_bus)
        engine.clock.speed = 0.001
        engine.load_events(events)

        async def delayed_stop() -> None:
            import asyncio

            await asyncio.sleep(0.01)
            engine.stop()

        import asyncio

        await asyncio.gather(engine.run(), delayed_stop())
        assert engine.is_running is False

    async def test_clock_property(self, event_bus: EventBus, events: list[BarCloseEvent]) -> None:
        clock = ReplayClock()
        engine = ReplayEngine(event_bus=event_bus, clock=clock)
        assert engine.clock is clock
        assert engine.total_events == 0
        _ = events

    async def test_run_sorted_by_timestamp(
        self, event_bus: EventBus, events: list[BarCloseEvent]
    ) -> None:
        unsorted = [events[2], events[0], events[1]]
        collected: list[BaseEvent] = []

        async def collector(event: BaseEvent) -> None:
            collected.append(event)

        event_bus.subscribe_all(collector, name="collector")

        engine = ReplayEngine(event_bus=event_bus)
        engine.clock.speed = 1000
        engine.load_events(unsorted)
        await engine.run()
        await event_bus.drain()

        bar_events = [e for e in collected if isinstance(e, BarCloseEvent)]
        assert len(bar_events) == 3
        assert bar_events[0].close == 150.5
        assert bar_events[2].close == 152
