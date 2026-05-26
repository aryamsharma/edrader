from __future__ import annotations

from collections import deque

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BarCloseEvent,
    BaseEvent,
)
from trading_platform.strategies.base import Strategy


class SmaCrossoverStrategy(Strategy):
    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
        fast_window: int = 10,
        slow_window: int = 30,
        default_size: int = 100,
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self._fast_window = fast_window
        self._slow_window = slow_window
        self._default_size = default_size
        self._prices: dict[str, deque[float]] = {}
        self._prev_fast_sma: dict[str, float] = {}
        self._prev_slow_sma: dict[str, float] = {}

    @property
    def fast_window(self) -> int:
        return self._fast_window

    @property
    def slow_window(self) -> int:
        return self._slow_window

    def event_types(self) -> list[type[BaseEvent]]:
        return [BarCloseEvent]

    async def on_event(self, event: BaseEvent) -> None:
        if not isinstance(event, BarCloseEvent):
            return
        await self._on_bar_close(event)

    async def _on_bar_close(self, event: BarCloseEvent) -> None:
        symbol = event.symbol
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self._slow_window)
            self._prev_fast_sma[symbol] = 0.0
            self._prev_slow_sma[symbol] = 0.0

        self._prices[symbol].append(event.close)

        if len(self._prices[symbol]) < self._slow_window:
            return

        fast_sma = self._compute_sma(symbol, self._fast_window)
        slow_sma = self._compute_sma(symbol, self._slow_window)

        if self._prev_fast_sma[symbol] <= self._prev_slow_sma[symbol] and fast_sma > slow_sma:
            await self.emit_signal(
                symbol,
                "BUY",
                confidence=0.8,
                suggested_size=self._default_size,
            )
        elif self._prev_fast_sma[symbol] >= self._prev_slow_sma[symbol] and fast_sma < slow_sma:
            await self.emit_signal(
                symbol,
                "SELL",
                confidence=0.8,
                suggested_size=self._default_size,
            )

        self._prev_fast_sma[symbol] = fast_sma
        self._prev_slow_sma[symbol] = slow_sma

    def _compute_sma(self, symbol: str, window: int) -> float:
        prices = list(self._prices[symbol])
        if len(prices) < window:
            return 0.0
        relevant = prices[-window:]
        return sum(relevant) / window
