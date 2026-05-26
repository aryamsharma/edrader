from __future__ import annotations

from collections import deque

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BarCloseEvent,
    BaseEvent,
)
from trading_platform.strategies.base import Strategy


class MeanReversionStrategy(Strategy):
    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
        window: int = 20,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        default_size: int = 100,
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self._window = window
        self._entry_z = entry_z
        self._exit_z = exit_z
        self._default_size = default_size
        self._prices: dict[str, deque[float]] = {}
        self._position_side: dict[str, str | None] = {}

    @property
    def window(self) -> int:
        return self._window

    @property
    def entry_z(self) -> float:
        return self._entry_z

    @property
    def exit_z(self) -> float:
        return self._exit_z

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
            self._position_side[symbol] = None

        self._prices[symbol].append(event.close)

        if len(self._prices[symbol]) < self._window:
            return

        mean, std = self._compute_stats(symbol)
        if std == 0.0:
            return

        z_score = (event.close - mean) / std
        current_side = self._position_side.get(symbol)

        if current_side is None and z_score <= -self._entry_z:
            await self.emit_signal(
                symbol,
                "BUY",
                confidence=0.7,
                suggested_size=self._default_size,
            )
            self._position_side[symbol] = "LONG"

        elif current_side is None and z_score >= self._entry_z:
            await self.emit_signal(
                symbol,
                "SELL",
                confidence=0.7,
                suggested_size=self._default_size,
            )
            self._position_side[symbol] = "SHORT"

        elif current_side == "LONG" and z_score >= -self._exit_z:
            await self.emit_signal(
                symbol,
                "SELL",
                confidence=0.9,
                suggested_size=self._default_size,
            )
            self._position_side[symbol] = None

        elif current_side == "SHORT" and z_score <= self._exit_z:
            await self.emit_signal(
                symbol,
                "BUY",
                confidence=0.9,
                suggested_size=self._default_size,
            )
            self._position_side[symbol] = None

    def _compute_stats(self, symbol: str) -> tuple[float, float]:
        prices = list(self._prices[symbol])
        n = len(prices)
        if n == 0:
            return 0.0, 0.0
        mean = sum(prices) / n
        variance = sum((p - mean) ** 2 for p in prices) / n
        std = variance**0.5
        return mean, std
