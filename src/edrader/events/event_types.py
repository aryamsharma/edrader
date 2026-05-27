from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any


class EventPriority(Enum):
    LOW = auto()
    NORMAL = auto()
    HIGH = auto()
    CRITICAL = auto()


@dataclass(frozen=True, slots=True)
class BaseEvent:
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "event_type": type(self).__name__,
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority.name,
            "correlation_id": self.correlation_id,
            "source": self.source,
        }
        for f in self._non_base_fields():
            value = getattr(self, f)
            if isinstance(value, Enum):
                result[f] = value.name
            else:
                result[f] = value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseEvent:
        import importlib

        event_type_name = data.pop("event_type", cls.__name__)
        module = importlib.import_module("edrader.events.event_types")
        event_class = getattr(module, event_type_name, cls)

        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        if "priority" in data and isinstance(data["priority"], str):
            data["priority"] = EventPriority[data["priority"]]

        return event_class(**data)

    @classmethod
    def _non_base_fields(cls) -> list[str]:
        base = {"event_id", "timestamp", "priority", "correlation_id", "source"}
        return [f.name for f in cls.__dataclass_fields__.values() if f.name not in base]


@dataclass(frozen=True, slots=True)
class MarketTickEvent(BaseEvent):
    symbol: str = ""
    price: float = 0.0
    volume: int = 0
    bid: float = 0.0
    ask: float = 0.0


@dataclass(frozen=True, slots=True)
class BarCloseEvent(BaseEvent):
    symbol: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0


@dataclass(frozen=True, slots=True)
class MarketOpenEvent(BaseEvent):
    symbol: str = ""


@dataclass(frozen=True, slots=True)
class MarketCloseEvent(BaseEvent):
    symbol: str = ""


@dataclass(frozen=True, slots=True)
class SignalGeneratedEvent(BaseEvent):
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    confidence: float = 0.0
    suggested_size: int = 0


@dataclass(frozen=True, slots=True)
class SignalApprovedEvent(BaseEvent):
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    confidence: float = 0.0
    suggested_size: int = 0


@dataclass(frozen=True, slots=True)
class SignalRejectedEvent(BaseEvent):
    strategy_id: str = ""
    symbol: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class StrategyErrorEvent(BaseEvent):
    strategy_id: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class RiskViolationEvent(BaseEvent):
    strategy_id: str = ""
    rule: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TradingHaltedEvent(BaseEvent):
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ExposureLimitEvent(BaseEvent):
    current_exposure: float = 0.0
    limit: float = 0.0


@dataclass(frozen=True, slots=True)
class ExposureUpdatedEvent(BaseEvent):
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    leverage: float = 0.0
    long_count: int = 0
    short_count: int = 0
    equity: float = 0.0


@dataclass(frozen=True, slots=True)
class OrderRequestedEvent(BaseEvent):
    symbol: str = ""
    side: str = ""
    quantity: int = 0
    order_type: str = ""
    limit_price: float | None = None


@dataclass(frozen=True, slots=True)
class OrderSubmittedEvent(BaseEvent):
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: int = 0
    order_type: str = ""
    limit_price: float | None = None


@dataclass(frozen=True, slots=True)
class OrderFilledEvent(BaseEvent):
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    fill_price: float = 0.0
    fill_quantity: int = 0


@dataclass(frozen=True, slots=True)
class OrderCancelledEvent(BaseEvent):
    order_id: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class OrderStatusChangedEvent(BaseEvent):
    order_id: str = ""
    status: str = ""


@dataclass(frozen=True, slots=True)
class PositionOpenedEvent(BaseEvent):
    symbol: str = ""
    quantity: int = 0
    avg_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class PositionClosedEvent(BaseEvent):
    symbol: str = ""
    realized_pnl: float = 0.0


@dataclass(frozen=True, slots=True)
class PnLUpdatedEvent(BaseEvent):
    symbol: str = ""
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


@dataclass(frozen=True, slots=True)
class AccountSummaryUpdate(BaseEvent):
    cash: float = 0.0
    buying_power: float = 0.0
    gross_position_value: float = 0.0
    net_liquidation: float = 0.0


@dataclass(frozen=True, slots=True)
class PositionUpdate(BaseEvent):
    symbol: str = ""
    position: int = 0
    avg_cost: float = 0.0
    market_price: float = 0.0


@dataclass(frozen=True, slots=True)
class BrokerDisconnectedEvent(BaseEvent):
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BrokerReconnectedEvent(BaseEvent):
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class HeartbeatEvent(BaseEvent):
    pass


@dataclass(frozen=True, slots=True)
class AlertEvent(BaseEvent):
    alert_type: str = ""
    message: str = ""
    severity: str = "INFO"
