from __future__ import annotations

from edrader.monitoring.logging import get_logger

logger = get_logger(__name__)


class SizingEngine:
    def __init__(
        self,
        method: str = "fixed",
        percent_equity_fraction: float = 0.02,
    ) -> None:
        self._method = method
        self._percent_equity_fraction = percent_equity_fraction
        self._atr_cache: dict[str, float] = {}

    @property
    def method(self) -> str:
        return self._method

    def update_atr(self, symbol: str, atr: float) -> None:
        self._atr_cache[symbol] = atr

    def compute_size(
        self,
        suggested_size: int,
        method: str | None = None,
        price: float | None = None,
        equity: float | None = None,
        symbol: str | None = None,
    ) -> int:
        actual_method = method or self._method
        if actual_method == "percent_equity":
            return self._percent_equity_size(suggested_size, price, equity)
        if actual_method == "volatility":
            return self._volatility_size(suggested_size, price, symbol, equity)
        return suggested_size

    def _percent_equity_size(
        self,
        suggested_size: int,
        price: float | None,
        equity: float | None,
    ) -> int:
        if equity is None or equity <= 0:
            return suggested_size
        if price is None or price <= 0:
            return suggested_size
        max_risk_amount = equity * self._percent_equity_fraction
        computed = int(max_risk_amount / price)
        return max(1, computed)

    def _volatility_size(
        self,
        suggested_size: int,
        price: float | None,
        symbol: str | None = None,
        equity: float | None = None,
    ) -> int:
        if price is None or price <= 0:
            return suggested_size
        if symbol is None or symbol not in self._atr_cache:
            return suggested_size
        atr = self._atr_cache[symbol]
        if atr <= 0:
            return suggested_size
        if equity is not None and equity > 0:
            risk_amount = equity * self._percent_equity_fraction
            computed = int(risk_amount / atr)
            return max(1, computed)
        atr_pct = atr / price
        if atr_pct <= 0:
            return suggested_size
        scaled = int(suggested_size / atr_pct)
        return max(1, scaled)
