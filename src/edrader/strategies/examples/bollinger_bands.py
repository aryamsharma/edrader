from __future__ import annotations

import math
from collections import deque

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BarCloseEvent,
    BaseEvent,
)
from edrader.strategies.base import Strategy


class BollingerBandsStrategy(Strategy):
    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
        window: int = 20,
        num_std: float = 2.0,
        default_size: int = 100,
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self._window = window
        self._num_std = num_std
        self._default_size = default_size
        self._prices: dict[str, deque[float]] = {}

    @property
    def window(self) -> int:
        return self._window

    @property
    def num_std(self) -> float:
        return self._num_std

    def event_types(self) -> list[type[BaseEvent]]:
        return [BarCloseEvent]

    async def on_event(self, event: BaseEvent) -> None:
        if not isinstance(event, BarCloseEvent):
            return
        await self._on_bar_close(event)

    async def _on_bar_close(self, event: BarCloseEvent) -> None:
        symbol = event.symbol
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self._window)

        self._prices[symbol].append(event.close)

        if len(self._prices[symbol]) < self._window:
            return

        sma = self._compute_sma(symbol)
        std = self._compute_std(symbol)
        upper = sma + self._num_std * std
        lower = sma - self._num_std * std

        if event.close <= lower:
            await self.emit_signal(
                symbol,
                "BUY",
                confidence=0.7,
                suggested_size=self._default_size,
            )
        elif event.close >= upper:
            await self.emit_signal(
                symbol,
                "SELL",
                confidence=0.7,
                suggested_size=self._default_size,
            )

    def _compute_sma(self, symbol: str) -> float:
        prices = list(self._prices[symbol])
        if len(prices) == 0:
            return 0.0
        return sum(prices) / len(prices)

    def _compute_std(self, symbol: str) -> float:
        prices = list(self._prices[symbol])
        n = len(prices)
        if n == 0:
            return 0.0
        mean = sum(prices) / n
        variance = sum((p - mean) ** 2 for p in prices) / n
        return math.sqrt(variance)
