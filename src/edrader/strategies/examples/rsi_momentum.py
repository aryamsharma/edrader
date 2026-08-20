from __future__ import annotations

from collections import deque

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BarCloseEvent,
    BaseEvent,
)
from edrader.strategies.base import Strategy


class RsiMomentumStrategy(Strategy):
    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
        window: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        default_size: int = 100,
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self._window = window
        self._oversold = oversold
        self._overbought = overbought
        self._default_size = default_size
        self._deltas: dict[str, deque[float]] = {}
        self._prev_close: dict[str, float] = {}

    @property
    def window(self) -> int:
        return self._window

    @property
    def oversold(self) -> float:
        return self._oversold

    @property
    def overbought(self) -> float:
        return self._overbought

    def event_types(self) -> list[type[BaseEvent]]:
        return [BarCloseEvent]

    async def on_event(self, event: BaseEvent) -> None:
        if not isinstance(event, BarCloseEvent):
            return
        await self._on_bar_close(event)

    async def _on_bar_close(self, event: BarCloseEvent) -> None:
        symbol = event.symbol
        if symbol not in self._deltas:
            self._deltas[symbol] = deque(maxlen=self._window)
            self._prev_close[symbol] = event.close
            return

        delta = event.close - self._prev_close[symbol]
        self._deltas[symbol].append(delta)
        self._prev_close[symbol] = event.close

        if len(self._deltas[symbol]) < self._window:
            return

        rsi = self._compute_rsi(symbol)

        if rsi < self._oversold:
            await self.emit_signal(
                symbol,
                "BUY",
                confidence=0.7,
                suggested_size=self._default_size,
            )
        elif rsi > self._overbought:
            await self.emit_signal(
                symbol,
                "SELL",
                confidence=0.7,
                suggested_size=self._default_size,
            )

    def _compute_rsi(self, symbol: str) -> float:
        deltas = list(self._deltas[symbol])
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0001
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
