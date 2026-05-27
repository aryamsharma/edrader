from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BarCloseEvent,
    BaseEvent,
    BrokerReconnectedEvent,
    MarketTickEvent,
)
from edrader.monitoring.logging import get_logger

logger = get_logger(__name__)


class BarAggregator:
    def __init__(self, symbol: str, bar_size_seconds: float = 60.0) -> None:
        self._symbol = symbol
        self._bar_size_seconds = bar_size_seconds
        self._bar_start: datetime | None = None
        self._open: float = 0.0
        self._high: float = 0.0
        self._low: float = 0.0
        self._close: float = 0.0
        self._volume: int = 0

    def add_tick(self, tick: MarketTickEvent) -> BarCloseEvent | None:
        now = tick.timestamp
        if self._bar_start is None:
            self._bar_start = now
            self._open = tick.price
            self._high = tick.price
            self._low = tick.price
            self._close = tick.price
            self._volume = tick.volume
            return None

        elapsed = (now - self._bar_start).total_seconds()
        if elapsed >= self._bar_size_seconds:
            bar = BarCloseEvent(
                symbol=self._symbol,
                open=self._open,
                high=self._high,
                low=self._low,
                close=self._close,
                volume=self._volume,
                timestamp=self._bar_start,
                source="market_data_feed",
            )
            self._bar_start = now
            self._open = tick.price
            self._high = tick.price
            self._low = tick.price
            self._close = tick.price
            self._volume = tick.volume
            return bar

        self._high = max(self._high, tick.price)
        self._low = min(self._low, tick.price) if self._low != 0.0 else tick.price
        self._close = tick.price
        self._volume += tick.volume
        return None

    def reset(self) -> None:
        self._bar_start = None
        self._open = 0.0
        self._high = 0.0
        self._low = 0.0
        self._close = 0.0
        self._volume = 0

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def bar_size_seconds(self) -> float:
        return self._bar_size_seconds


class MarketDataFeed:
    def __init__(
        self,
        ib: Any,
        event_bus: EventBus,
        default_bar_size_seconds: float = 60.0,
    ) -> None:
        self._ib = ib
        self._event_bus = event_bus
        self._default_bar_size_seconds = default_bar_size_seconds
        self._running = False
        self._subscriptions: dict[str, Any] = {}
        self._aggs: dict[str, BarAggregator] = {}
        self._handler_id: str | None = None
        self._reconnect_unsub: Any = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def subscriptions(self) -> list[str]:
        return list(self._subscriptions.keys())

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._handler_id = self._ib.pendingTickersEvent.connect(self._on_pending_tickers)
        self._reconnect_unsub = await self._subscribe_to_reconnect()
        logger.info("market_data_feed_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._handler_id is not None:
            self._ib.pendingTickersEvent.disconnect(self._handler_id)
            self._handler_id = None
        if self._reconnect_unsub is not None:
            self._reconnect_unsub()
            self._reconnect_unsub = None
        await self.unsubscribe_all()
        logger.info("market_data_feed_stopped")

    async def subscribe_symbol(
        self,
        symbol: str,
        exchange: str = "SMART",
        currency: str = "USD",
        sec_type: str = "STK",
        bar_size_seconds: float | None = None,
    ) -> None:
        if not self._running:
            raise RuntimeError("MarketDataFeed is not running")
        if symbol in self._subscriptions:
            return

        contract = self._make_contract(symbol, exchange, currency, sec_type)
        self._ib.reqMktData(contract)
        self._subscriptions[symbol] = contract

        bs = bar_size_seconds if bar_size_seconds is not None else self._default_bar_size_seconds
        self._aggs[symbol] = BarAggregator(symbol, bar_size_seconds=bs)

        logger.info("market_data_subscribed", symbol=symbol)

    async def subscribe_symbols(
        self,
        symbols: list[str],
        exchange: str = "SMART",
        currency: str = "USD",
        sec_type: str = "STK",
        bar_size_seconds: float | None = None,
    ) -> None:
        for symbol in symbols:
            await self.subscribe_symbol(
                symbol,
                exchange=exchange,
                currency=currency,
                sec_type=sec_type,
                bar_size_seconds=bar_size_seconds,
            )

    async def unsubscribe(self, symbol: str) -> None:
        if symbol not in self._subscriptions:
            return
        contract = self._subscriptions.pop(symbol)
        self._ib.cancelMktData(contract)
        self._aggs.pop(symbol, None)
        logger.info("market_data_unsubscribed", symbol=symbol)

    async def unsubscribe_all(self) -> None:
        for symbol in list(self._subscriptions):
            await self.unsubscribe(symbol)

    def _make_contract(self, symbol: str, exchange: str, currency: str, sec_type: str) -> Any:
        if sec_type == "STK":
            from ib_insync import Stock

            return Stock(symbol, exchange, currency)
        from ib_insync import Contract

        return Contract(symbol, sec_type, exchange, currency=currency)  # type: ignore[arg-type]

    def _on_pending_tickers(self) -> None:
        if not self._running:
            return
        tickers = list(self._ib.pendingTickers)
        if tickers:
            asyncio.create_task(self._process_tickers(tickers))

    async def _process_tickers(self, tickers: list[Any]) -> None:
        for ticker in tickers:
            symbol = ticker.contract.symbol
            if symbol not in self._subscriptions:
                continue

            event = self._ticker_to_event(ticker)
            if event is None:
                continue

            await self._event_bus.publish(event)

            bar_event = self._update_bar(symbol, event)
            if bar_event is not None:
                await self._event_bus.publish(bar_event)

    def _ticker_to_event(self, ticker: Any) -> MarketTickEvent | None:
        symbol = ticker.contract.symbol
        price = float(ticker.last) if ticker.last else 0.0
        volume = int(ticker.volume) if ticker.volume else 0
        bid = float(ticker.bid) if ticker.bid else 0.0
        ask = float(ticker.ask) if ticker.ask else 0.0

        if price == 0.0 and bid == 0.0 and ask == 0.0:
            return None

        ts = ticker.time if ticker.time else datetime.now(UTC)

        return MarketTickEvent(
            symbol=symbol,
            price=price,
            volume=volume,
            bid=bid,
            ask=ask,
            timestamp=ts,
            source="market_data_feed",
        )

    def _update_bar(self, symbol: str, tick: MarketTickEvent) -> BarCloseEvent | None:
        agg = self._aggs.get(symbol)
        if agg is None:
            return None
        return agg.add_tick(tick)

    async def _subscribe_to_reconnect(self) -> Any:
        async def on_reconnect(_event: BaseEvent) -> None:
            await self._re_subscribe_all()

        self._event_bus.subscribe(BrokerReconnectedEvent, on_reconnect, name="feed_reconnect")
        return lambda: self._event_bus.unsubscribe(BrokerReconnectedEvent, on_reconnect)

    async def _re_subscribe_all(self) -> None:
        symbols = list(self._subscriptions.keys())
        for symbol in symbols:
            contract = self._subscriptions.pop(symbol)
            self._ib.cancelMktData(contract)
        self._aggs.clear()

        for symbol in symbols:
            contract = self._make_contract(symbol, "SMART", "USD", "STK")
            self._ib.reqMktData(contract)
            self._subscriptions[symbol] = contract
            self._aggs[symbol] = BarAggregator(
                symbol, bar_size_seconds=self._default_bar_size_seconds
            )
        logger.info("market_data_resubscribed", symbols=symbols)
