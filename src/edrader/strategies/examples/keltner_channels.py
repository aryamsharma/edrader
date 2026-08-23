from __future__ import annotations

from collections import deque

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BarCloseEvent,
    BaseEvent,
)
from edrader.strategies.base import Strategy


class KeltnerChannelsStrategy(Strategy):
    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
        ema_window: int = 20,
        atr_window: int = 14,
        multiplier: float = 2.0,
        default_size: int = 100,
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self._ema_window = ema_window
        self._atr_window = atr_window
        self._multiplier = multiplier
        self._default_size = default_size
        self._ema: dict[str, float] = {}
        self._prev_close: dict[str, float] = {}
        self._true_ranges: dict[str, deque[float]] = {}

    @property
    def ema_window(self) -> int:
        return self._ema_window

    @property
    def atr_window(self) -> int:
        return self._atr_window

    @property
    def multiplier(self) -> float:
        return self._multiplier

    def event_types(self) -> list[type[BaseEvent]]:
        return [BarCloseEvent]

    async def on_event(self, event: BaseEvent) -> None:
        if not isinstance(event, BarCloseEvent):
            return
        await self._on_bar_close(event)

    async def _on_bar_close(self, event: BarCloseEvent) -> None:
        symbol = event.symbol
        if symbol not in self._true_ranges:
            self._true_ranges[symbol] = deque(maxlen=self._atr_window)
            self._ema[symbol] = event.close
            self._prev_close[symbol] = event.close
            return

        prev_close = self._prev_close[symbol]
        true_range = max(
            event.high - event.low,
            abs(event.high - prev_close),
            abs(event.low - prev_close),
        )
        self._true_ranges[symbol].append(true_range)

        k = 2.0 / (self._ema_window + 1)
        self._ema[symbol] = event.close * k + self._ema[symbol] * (1.0 - k)
        self._prev_close[symbol] = event.close

        if len(self._true_ranges[symbol]) < self._atr_window:
            return

        trs = list(self._true_ranges[symbol])
        atr = sum(trs) / len(trs)
        ema = self._ema[symbol]
        upper = ema + self._multiplier * atr
        lower = ema - self._multiplier * atr

        if event.close > upper:
            await self.emit_signal(
                symbol,
                "BUY",
                confidence=0.7,
                suggested_size=self._default_size,
            )
        elif event.close < lower:
            await self.emit_signal(
                symbol,
                "SELL",
                confidence=0.7,
                suggested_size=self._default_size,
            )
