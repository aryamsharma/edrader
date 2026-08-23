from __future__ import annotations

from collections import deque

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BarCloseEvent,
    BaseEvent,
)
from edrader.strategies.base import Strategy


class IchimokuCloudStrategy(Strategy):
    def __init__(
        self,
        strategy_id: str,
        event_bus: EventBus,
        tenkan_window: int = 9,
        kijun_window: int = 26,
        senkou_b_window: int = 52,
        default_size: int = 100,
    ) -> None:
        super().__init__(strategy_id, event_bus)
        self._tenkan_window = tenkan_window
        self._kijun_window = kijun_window
        self._senkou_b_window = senkou_b_window
        self._default_size = default_size
        self._highs: dict[str, deque[float]] = {}
        self._lows: dict[str, deque[float]] = {}
        self._prev_tenkan: dict[str, float] = {}
        self._prev_kijun: dict[str, float] = {}

    @property
    def tenkan_window(self) -> int:
        return self._tenkan_window

    @property
    def kijun_window(self) -> int:
        return self._kijun_window

    @property
    def senkou_b_window(self) -> int:
        return self._senkou_b_window

    def event_types(self) -> list[type[BaseEvent]]:
        return [BarCloseEvent]

    async def on_event(self, event: BaseEvent) -> None:
        if not isinstance(event, BarCloseEvent):
            return
        await self._on_bar_close(event)

    async def _on_bar_close(self, event: BarCloseEvent) -> None:
        symbol = event.symbol
        max_window = max(self._tenkan_window, self._kijun_window, self._senkou_b_window)

        if symbol not in self._highs:
            self._highs[symbol] = deque(maxlen=max_window)
            self._lows[symbol] = deque(maxlen=max_window)
            self._prev_tenkan[symbol] = 0.0
            self._prev_kijun[symbol] = 0.0

        self._highs[symbol].append(event.high)
        self._lows[symbol].append(event.low)

        if len(self._lows[symbol]) < self._kijun_window:
            return

        highs = list(self._highs[symbol])
        lows = list(self._lows[symbol])

        tenkan_highs = highs[-self._tenkan_window :]
        tenkan_lows = lows[-self._tenkan_window :]
        tenkan = (max(tenkan_highs) + min(tenkan_lows)) / 2.0

        kijun_highs = highs[-self._kijun_window :]
        kijun_lows = lows[-self._kijun_window :]
        kijun = (max(kijun_highs) + min(kijun_lows)) / 2.0

        senkou_a = (tenkan + kijun) / 2.0

        if len(self._lows[symbol]) < self._senkou_b_window:
            self._prev_tenkan[symbol] = tenkan
            self._prev_kijun[symbol] = kijun
            return

        senkou_b_highs = highs[-self._senkou_b_window :]
        senkou_b_lows = lows[-self._senkou_b_window :]
        senkou_b = (max(senkou_b_highs) + min(senkou_b_lows)) / 2.0

        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)

        prev_tenkan = self._prev_tenkan[symbol]
        prev_kijun = self._prev_kijun[symbol]

        if prev_tenkan <= prev_kijun and tenkan > kijun and event.close > cloud_top:
            await self.emit_signal(
                symbol,
                "BUY",
                confidence=0.7,
                suggested_size=self._default_size,
            )
        elif prev_tenkan >= prev_kijun and tenkan < kijun and event.close < cloud_bottom:
            await self.emit_signal(
                symbol,
                "SELL",
                confidence=0.7,
                suggested_size=self._default_size,
            )

        self._prev_tenkan[symbol] = tenkan
        self._prev_kijun[symbol] = kijun
