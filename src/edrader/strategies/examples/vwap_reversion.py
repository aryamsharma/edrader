from __future__ import annotations

from collections import deque

from edrader.events.bus import EventBus
from edrader.events.event_types import BaseEvent, MarketTickEvent
from edrader.strategies.base import Strategy


class VwapReversionStrategy(Strategy):
    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
        window: int = 100,
        entry_pct: float = 0.01,
        exit_pct: float = 0.002,
        default_size: int = 100,
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self._window = window
        self._entry_pct = entry_pct
        self._exit_pct = exit_pct
        self._default_size = default_size
        self._prices: dict[str, deque[float]] = {}
        self._volumes: dict[str, deque[int]] = {}
        self._cum_pv: dict[str, float] = {}
        self._cum_vol: dict[str, int] = {}
        self._last_signal: dict[str, str] = {}

    @property
    def window(self) -> int:
        return self._window

    def event_types(self) -> list[type[BaseEvent]]:
        return [MarketTickEvent]

    async def on_event(self, event: BaseEvent) -> None:
        if not isinstance(event, MarketTickEvent):
            return
        await self._on_tick(event)

    async def _on_tick(self, event: MarketTickEvent) -> None:
        symbol = event.symbol
        if event.volume <= 0 or event.price <= 0:
            return

        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self._window)
            self._volumes[symbol] = deque(maxlen=self._window)
            self._cum_pv[symbol] = 0.0
            self._cum_vol[symbol] = 0

        old_price = self._prices[symbol][0] if len(self._prices[symbol]) == self._window else None
        old_vol = self._volumes[symbol][0] if len(self._volumes[symbol]) == self._window else None

        self._prices[symbol].append(event.price)
        self._volumes[symbol].append(event.volume)

        self._cum_pv[symbol] += event.price * event.volume
        self._cum_vol[symbol] += event.volume

        if old_price is not None and old_vol is not None:
            self._cum_pv[symbol] -= old_price * old_vol
            self._cum_vol[symbol] -= old_vol

        if self._cum_vol[symbol] <= 0:
            return

        vwap = self._cum_pv[symbol] / self._cum_vol[symbol]
        deviation = (event.price - vwap) / vwap
        last = self._last_signal.get(symbol)

        if deviation > self._entry_pct and last != "SELL":
            await self.emit_signal(
                symbol, "SELL", confidence=0.7, suggested_size=self._default_size
            )
            self._last_signal[symbol] = "SELL"
        elif deviation < -self._entry_pct and last != "BUY":
            await self.emit_signal(symbol, "BUY", confidence=0.7, suggested_size=self._default_size)
            self._last_signal[symbol] = "BUY"

        if last is not None and abs(deviation) < self._exit_pct:
            opposite = "BUY" if last == "SELL" else "SELL"
            await self.emit_signal(
                symbol, opposite, confidence=0.5, suggested_size=self._default_size
            )
            del self._last_signal[symbol]
