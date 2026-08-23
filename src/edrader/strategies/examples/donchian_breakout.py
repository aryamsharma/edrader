from __future__ import annotations

from collections import deque

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BarCloseEvent,
    BaseEvent,
)
from edrader.strategies.base import Strategy


class DonchianBreakoutStrategy(Strategy):
    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
        window: int = 20,
        default_size: int = 100,
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self._window = window
        self._default_size = default_size
        self._prices: dict[str, deque[float]] = {}

    @property
    def window(self) -> int:
        return self._window

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

        prices = list(self._prices[symbol])
        upper = max(prices)
        lower = min(prices)

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
