from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from trading_platform.broker.market_data import MarketDataFeed
from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BarCloseEvent,
    BrokerReconnectedEvent,
    MarketTickEvent,
)


def _make_ticker(
    symbol: str,
    last: float = 0.0,
    volume: int = 0,
    bid: float = 0.0,
    ask: float = 0.0,
) -> MagicMock:
    ticker = MagicMock()
    ticker.contract.symbol = symbol
    ticker.last = last
    ticker.volume = volume
    ticker.bid = bid
    ticker.ask = ask
    ticker.time = datetime.now(UTC)
    return ticker


@pytest.fixture
def mock_ib() -> MagicMock:
    ib = MagicMock()
    ib.reqMktData = MagicMock()
    ib.reqMktData.return_value = MagicMock()
    ib.cancelMktData = MagicMock()
    ib.pendingTickersEvent = MagicMock()
    ib.pendingTickersEvent.connect = MagicMock(return_value="handler_id")
    ib.pendingTickersEvent.disconnect = MagicMock()
    ib.disconnectedEvent = MagicMock()
    ib.disconnectedEvent.connect = MagicMock(return_value="handler_id")
    ib.disconnectedEvent.disconnect = MagicMock()
    ib.connectedEvent = MagicMock()
    ib.connectedEvent.connect = MagicMock(return_value="handler_id")
    return ib


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
async def feed(
    mock_ib: MagicMock,
    event_bus: EventBus,
) -> MarketDataFeed:
    f = MarketDataFeed(ib=mock_ib, event_bus=event_bus, default_bar_size_seconds=60)
    yield f
    if f.is_running:
        await f.stop()


class TestMarketDataFeedSubscribe:
    async def test_initial_state(self, feed: MarketDataFeed) -> None:
        assert feed.is_running is False
        assert feed.subscriptions == []

    async def test_subscribe_symbol_adds_to_subscriptions(self, feed: MarketDataFeed) -> None:
        await feed.start()
        await feed.subscribe_symbol("AAPL")
        assert "AAPL" in feed.subscriptions

    async def test_subscribe_symbol_calls_req_mkt_data(
        self, feed: MarketDataFeed, mock_ib: MagicMock
    ) -> None:
        await feed.start()
        await feed.subscribe_symbol("AAPL")
        mock_ib.reqMktData.assert_called_once()
        args, _ = mock_ib.reqMktData.call_args
        contract = args[0]
        assert contract.symbol == "AAPL"

    async def test_subscribe_symbols_batch(self, feed: MarketDataFeed, mock_ib: MagicMock) -> None:
        await feed.start()
        await feed.subscribe_symbols(["AAPL", "MSFT"])
        assert set(feed.subscriptions) == {"AAPL", "MSFT"}
        assert mock_ib.reqMktData.call_count == 2

    async def test_subscribe_duplicate_symbol(
        self, feed: MarketDataFeed, mock_ib: MagicMock
    ) -> None:
        await feed.start()
        await feed.subscribe_symbol("AAPL")
        await feed.subscribe_symbol("AAPL")
        assert feed.subscriptions == ["AAPL"]
        assert mock_ib.reqMktData.call_count == 1

    async def test_subscribe_before_start_raises(self, feed: MarketDataFeed) -> None:
        with pytest.raises(RuntimeError, match="not running"):
            await feed.subscribe_symbol("AAPL")

    async def test_unsubscribe_removes_symbol(
        self, feed: MarketDataFeed, mock_ib: MagicMock
    ) -> None:
        await feed.start()
        await feed.subscribe_symbol("AAPL")
        await feed.subscribe_symbol("MSFT")
        await feed.unsubscribe("AAPL")
        assert feed.subscriptions == ["MSFT"]
        mock_ib.cancelMktData.assert_called_once()

    async def test_unsubscribe_nonexistent_symbol(self, feed: MarketDataFeed) -> None:
        await feed.start()
        await feed.subscribe_symbol("AAPL")
        await feed.unsubscribe("MSFT")
        assert feed.subscriptions == ["AAPL"]

    async def test_unsubscribe_all(self, feed: MarketDataFeed, mock_ib: MagicMock) -> None:
        await feed.start()
        await feed.subscribe_symbols(["AAPL", "MSFT"])
        await feed.unsubscribe_all()
        assert feed.subscriptions == []
        assert mock_ib.cancelMktData.call_count == 2


class TestMarketDataFeedTickHandling:
    async def _process_tickers(self, feed: MarketDataFeed, ticker: MagicMock) -> None:
        await feed._process_tickers([ticker])

    async def test_tick_handler_emits_market_tick_event(
        self,
        feed: MarketDataFeed,
        collected_events: list,
        event_bus: EventBus,
    ) -> None:
        await feed.start()
        await feed.subscribe_symbol("AAPL")

        ticker = _make_ticker("AAPL", last=150.25, volume=1000, bid=150.20, ask=150.30)
        await feed._process_tickers([ticker])
        await event_bus.drain()

        ticks = [e for e in collected_events if isinstance(e, MarketTickEvent)]
        assert len(ticks) >= 1
        assert ticks[0].symbol == "AAPL"
        assert ticks[0].price == 150.25
        assert ticks[0].volume == 1000

    async def test_tick_handler_with_bid_ask(
        self,
        feed: MarketDataFeed,
        collected_events: list,
        event_bus: EventBus,
    ) -> None:
        await feed.start()
        await feed.subscribe_symbol("AAPL")

        ticker = _make_ticker("AAPL", last=0.0, volume=0, bid=150.20, ask=150.30)
        await feed._process_tickers([ticker])
        await event_bus.drain()

        ticks = [e for e in collected_events if isinstance(e, MarketTickEvent)]
        assert len(ticks) >= 1
        assert ticks[0].bid == 150.20
        assert ticks[0].ask == 150.30

    async def test_tick_handler_ignores_unsubscribed_symbol(
        self,
        feed: MarketDataFeed,
        collected_events: list,
        event_bus: EventBus,
    ) -> None:
        await feed.start()
        await feed.subscribe_symbol("AAPL")

        ticker = _make_ticker("MSFT", last=300.0, volume=500, bid=299.0, ask=301.0)
        await feed._process_tickers([ticker])
        await event_bus.drain()

        ticks = [e for e in collected_events if isinstance(e, MarketTickEvent)]
        assert len(ticks) == 0

    async def test_tick_handler_sets_up_on_start(
        self, feed: MarketDataFeed, mock_ib: MagicMock
    ) -> None:
        await feed.start()
        mock_ib.pendingTickersEvent.connect.assert_called_once()


class TestMarketDataFeedBarAggregation:
    async def test_bar_aggregator_emits_bar_close(
        self,
        feed: MarketDataFeed,
        collected_events: list,
        event_bus: EventBus,
    ) -> None:
        feed._default_bar_size_seconds = 0.1
        await feed.start()
        await feed.subscribe_symbol("AAPL")

        for price in [100.0, 101.0, 99.0, 100.5]:
            ticker = _make_ticker("AAPL", last=price, volume=100, bid=price - 0.1, ask=price + 0.1)
            await feed._process_tickers([ticker])
            await asyncio.sleep(0.04)

        await event_bus.drain()

        bars = [e for e in collected_events if isinstance(e, BarCloseEvent)]
        assert len(bars) >= 1
        assert bars[0].symbol == "AAPL"
        assert bars[0].open == 100.0
        assert bars[0].high == 101.0
        assert bars[0].low == 99.0
        assert bars[0].close == 99.0
        assert bars[0].volume == 300

    async def test_bar_aggregator_no_event_before_window(
        self,
        feed: MarketDataFeed,
        collected_events: list,
        event_bus: EventBus,
    ) -> None:
        feed._default_bar_size_seconds = 3600
        await feed.start()
        await feed.subscribe_symbol("AAPL")

        ticker = _make_ticker("AAPL", last=100.0, volume=100, bid=99.9, ask=100.1)
        await feed._process_tickers([ticker])

        await event_bus.drain()

        bars = [e for e in collected_events if isinstance(e, BarCloseEvent)]
        assert len(bars) == 0

    async def test_bar_aggregator_resets_after_bar(
        self,
        feed: MarketDataFeed,
        collected_events: list,
        event_bus: EventBus,
    ) -> None:
        feed._default_bar_size_seconds = 0.1
        await feed.start()
        await feed.subscribe_symbol("AAPL")

        ticker = _make_ticker("AAPL", last=100.0, volume=100, bid=99.9, ask=100.1)
        await feed._process_tickers([ticker])
        await asyncio.sleep(0.12)

        ticker2 = _make_ticker("AAPL", last=101.0, volume=50, bid=100.9, ask=101.1)
        await feed._process_tickers([ticker2])
        await event_bus.drain()

        bars = [e for e in collected_events if isinstance(e, BarCloseEvent)]
        assert len(bars) >= 1
        assert bars[0].close == 100.0


class TestMarketDataFeedLifecycle:
    async def test_start_sets_running(self, feed: MarketDataFeed) -> None:
        await feed.start()
        assert feed.is_running is True

    async def test_stop_clears_subscriptions(self, feed: MarketDataFeed) -> None:
        await feed.start()
        await feed.subscribe_symbols(["AAPL", "MSFT"])
        await feed.stop()
        assert feed.is_running is False
        assert feed.subscriptions == []

    async def test_stop_disconnects_handler(self, feed: MarketDataFeed, mock_ib: MagicMock) -> None:
        await feed.start()
        await feed.stop()
        mock_ib.pendingTickersEvent.disconnect.assert_called_once_with("handler_id")

    async def test_re_subscribe_on_reconnect(
        self,
        feed: MarketDataFeed,
        mock_ib: MagicMock,
        event_bus: EventBus,
    ) -> None:
        await feed.start()
        await feed.subscribe_symbols(["AAPL", "MSFT"])
        initial_calls = mock_ib.reqMktData.call_count

        await event_bus.publish(BrokerReconnectedEvent(attempts=0, source="ibkr_client"))
        await event_bus.drain()

        assert mock_ib.reqMktData.call_count == initial_calls * 2

    async def test_start_idempotent(self, feed: MarketDataFeed) -> None:
        await feed.start()
        await feed.start()
        assert feed.is_running is True

    async def test_stop_idempotent(self, feed: MarketDataFeed) -> None:
        await feed.start()
        await feed.stop()
        await feed.stop()
        assert feed.is_running is False

    async def test_subscribe_symbol_with_bar_size(
        self, feed: MarketDataFeed, collected_events: list, event_bus: EventBus
    ) -> None:
        feed._default_bar_size_seconds = 0.05
        await feed.start()
        await feed.subscribe_symbol("AAPL", bar_size_seconds=0.05)

        ticker = _make_ticker("AAPL", last=100.0, volume=100, bid=99.9, ask=100.1)
        await feed._process_tickers([ticker])
        await asyncio.sleep(0.06)

        ticker2 = _make_ticker("AAPL", last=101.0, volume=100, bid=100.9, ask=101.1)
        await feed._process_tickers([ticker2])
        await event_bus.drain()

        bars = [e for e in collected_events if isinstance(e, BarCloseEvent)]
        assert len(bars) >= 1
