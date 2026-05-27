from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BaseEvent,
    ExposureUpdatedEvent,
    OrderFilledEvent,
    PositionClosedEvent,
)
from trading_platform.monitoring.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestMetrics:
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    turnover: float = 0.0
    start_equity: float = 0.0
    end_equity: float = 0.0
    peak_equity: float = 0.0


class MetricsEngine:
    def __init__(
        self,
        event_bus: EventBus,
        initial_capital: float = 100_000.0,
        risk_free_rate: float = 0.05,
    ) -> None:
        self._event_bus = event_bus
        self._initial_capital = initial_capital
        self._risk_free_rate = risk_free_rate
        self._running = False
        self._equity_curve: list[tuple[datetime, float]] = []
        self._winning_trades: int = 0
        self._losing_trades: int = 0
        self._total_traded_value: float = 0.0
        self._exposure_unsub: Any = None
        self._fill_unsub: Any = None
        self._close_unsub: Any = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._exposure_unsub = await self._subscribe_exposure()
        self._fill_unsub = await self._subscribe_fills()
        self._close_unsub = await self._subscribe_closes()
        logger.info("metrics_engine_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for unsub in (self._exposure_unsub, self._fill_unsub, self._close_unsub):
            if unsub is not None:
                unsub()
        self._exposure_unsub = None
        self._fill_unsub = None
        self._close_unsub = None
        logger.info("metrics_engine_stopped")

    def compute(self) -> BacktestMetrics:
        total_trades = self._winning_trades + self._losing_trades
        win_rate = self._winning_trades / total_trades if total_trades > 0 else 0.0

        if not self._equity_curve:
            return BacktestMetrics(
                win_rate=win_rate,
                total_trades=total_trades,
                winning_trades=self._winning_trades,
                losing_trades=self._losing_trades,
            )

        start_eq = self._equity_curve[0][1]
        end_eq = self._equity_curve[-1][1]
        peak_eq = max(eq for _, eq in self._equity_curve)

        total_return = (end_eq - start_eq) / start_eq if start_eq > 0 else 0.0

        total_seconds = (self._equity_curve[-1][0] - self._equity_curve[0][0]).total_seconds()
        years = total_seconds / (365.25 * 86400)
        annualized_return = self._compute_annualized_return(total_return, years)

        max_dd = self._compute_max_drawdown()

        avg_equity = sum(eq for _, eq in self._equity_curve) / len(self._equity_curve)
        turnover = self._total_traded_value / avg_equity if avg_equity > 0 else 0.0

        sharpe = self._compute_sharpe(years)

        return BacktestMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            total_trades=total_trades,
            winning_trades=self._winning_trades,
            losing_trades=self._losing_trades,
            turnover=turnover,
            start_equity=start_eq,
            end_equity=end_eq,
            peak_equity=peak_eq,
        )

    @staticmethod
    def _compute_annualized_return(total_return: float, years: float) -> float:
        if years <= 0 or total_return <= -1:
            return 0.0
        if years < 1 / 365:
            return total_return
        return (1 + total_return) ** (1 / years) - 1  # type: ignore[no-any-return]

    def _compute_max_drawdown(self) -> float:
        if len(self._equity_curve) < 2:
            return 0.0
        peak = self._equity_curve[0][1]
        max_dd = 0.0
        for _, eq in self._equity_curve:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd
        return max_dd

    def _compute_sharpe(self, years: float) -> float:
        if len(self._equity_curve) < 2 or years <= 0:
            return 0.0

        returns: list[float] = []
        for i in range(1, len(self._equity_curve)):
            prev_eq = self._equity_curve[i - 1][1]
            curr_eq = self._equity_curve[i][1]
            if prev_eq > 0:
                returns.append((curr_eq - prev_eq) / prev_eq)

        if len(returns) < 2:
            return 0.0

        n = len(returns)
        mean_r = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_r = math.sqrt(variance)

        if std_r == 0:
            return 0.0

        periods_per_year = n / years
        annualization = math.sqrt(periods_per_year)
        rf_per_period = self._risk_free_rate / periods_per_year if periods_per_year > 0 else 0.0
        excess_mean = mean_r - rf_per_period

        return excess_mean / std_r * annualization

    async def _on_exposure(self, event: BaseEvent) -> None:
        assert isinstance(event, ExposureUpdatedEvent)
        if not self._running:
            return
        self._equity_curve.append((event.timestamp, event.equity))

    async def _on_fill(self, event: BaseEvent) -> None:
        assert isinstance(event, OrderFilledEvent)
        if not self._running:
            return
        self._total_traded_value += event.fill_price * event.fill_quantity

    async def _on_close(self, event: BaseEvent) -> None:
        assert isinstance(event, PositionClosedEvent)
        if not self._running:
            return
        if event.realized_pnl > 0:
            self._winning_trades += 1
        elif event.realized_pnl < 0:
            self._losing_trades += 1

    async def _subscribe_exposure(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_exposure(event)

        self._event_bus.subscribe(ExposureUpdatedEvent, handler, name="metrics_engine_exposure")
        return lambda: self._event_bus.unsubscribe(ExposureUpdatedEvent, handler)

    async def _subscribe_fills(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_fill(event)

        self._event_bus.subscribe(OrderFilledEvent, handler, name="metrics_engine_fill")
        return lambda: self._event_bus.unsubscribe(OrderFilledEvent, handler)

    async def _subscribe_closes(self) -> Any:
        async def handler(event: BaseEvent) -> None:
            await self._on_close(event)

        self._event_bus.subscribe(PositionClosedEvent, handler, name="metrics_engine_close")
        return lambda: self._event_bus.unsubscribe(PositionClosedEvent, handler)
