from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto


class EventPriority(Enum):
    LOW = auto()
    NORMAL = auto()
    HIGH = auto()
    CRITICAL = auto()


@dataclass(frozen=True, slots=True)
class BaseEvent:
    event_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    priority: EventPriority = EventPriority.NORMAL

    def __post_init__(self) -> None:
        if not self.event_id:
            object.__setattr__(self, "event_id", f"{type(self).__name__}_{id(self)}")


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
class SignalGeneratedEvent(BaseEvent):
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    confidence: float = 0.0
    suggested_size: int = 0


@dataclass(frozen=True, slots=True)
class RiskViolationEvent(BaseEvent):
    strategy_id: str = ""
    rule: str = ""
    reason: str = ""


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
class PositionOpenedEvent(BaseEvent):
    symbol: str = ""
    quantity: int = 0
    avg_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class PositionClosedEvent(BaseEvent):
    symbol: str = ""
    realized_pnl: float = 0.0


@dataclass(frozen=True, slots=True)
class BrokerDisconnectedEvent(BaseEvent):
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BrokerReconnectedEvent(BaseEvent):
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class HeartbeatEvent(BaseEvent):
    pass
