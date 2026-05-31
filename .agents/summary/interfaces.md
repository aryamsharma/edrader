# Interfaces

## Domain Event Types (26 types in `src/edrader/events/event_types.py`)

All inherit from `BaseEvent` (frozen dataclass with slots, `to_dict()`/`from_dict()` serialization). EventPriority enum: `LOW`, `NORMAL` (default), `HIGH`, `CRITICAL`.

```python
@dataclass(frozen=True, slots=True)
class BaseEvent:
    event_id: str         # uuid.uuid4().hex[:16]
    timestamp: datetime   # datetime.now(UTC)
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod def from_dict(cls, data) -> BaseEvent: ...
```

### Market Data Events

| Event | Extra Fields |
|-------|-------------|
| `MarketTickEvent` | `symbol`, `price`, `volume`, `bid`, `ask` |
| `BarCloseEvent` | `symbol`, `open`, `high`, `low`, `close`, `volume` |
| `MarketOpenEvent` | `symbol` |
| `MarketCloseEvent` | `symbol` |

### Signal Events

| Event | Extra Fields |
|-------|-------------|
| `SignalGeneratedEvent` | `strategy_id`, `symbol`, `side`, `confidence`, `suggested_size` |
| `SignalApprovedEvent` | `strategy_id`, `symbol`, `side`, `confidence`, `suggested_size` |
| `SignalRejectedEvent` | `strategy_id`, `symbol`, `reason` |

### Order Events

| Event | Extra Fields |
|-------|-------------|
| `OrderRequestedEvent` | `symbol`, `side`, `quantity`, `order_type`, `limit_price` |
| `OrderSubmittedEvent` | `order_id`, `symbol`, `side`, `quantity`, `order_type`, `limit_price` |
| `OrderFilledEvent` | `order_id`, `symbol`, `side`, `fill_price`, `fill_quantity` |
| `OrderCancelledEvent` | `order_id`, `reason` |
| `OrderStatusChangedEvent` | `order_id`, `status` |

### Position Events

| Event | Extra Fields |
|-------|-------------|
| `PositionOpenedEvent` | `symbol`, `quantity`, `avg_cost` |
| `PositionClosedEvent` | `symbol`, `realized_pnl` |
| `PnLUpdatedEvent` | `symbol`, `unrealized_pnl`, `realized_pnl` |
| `ExposureUpdatedEvent` | `gross_exposure`, `net_exposure`, `leverage`, `long_count`, `short_count`, `equity` |
| `PositionUpdate` | `symbol`, `position`, `avg_cost`, `market_price` |
| `ExposureLimitEvent` | `current_exposure`, `limit` |

### Risk Events

| Event | Extra Fields |
|-------|-------------|
| `RiskViolationEvent` | `strategy_id`, `rule`, `reason` |
| `TradingHaltedEvent` | `reason` |

### System Events

| Event | Extra Fields |
|-------|-------------|
| `BrokerDisconnectedEvent` | `reason` |
| `BrokerReconnectedEvent` | `attempts` |
| `HeartbeatEvent` | — |
| `AlertEvent` | `alert_type`, `message`, `severity` |
| `StrategyErrorEvent` | `strategy_id`, `error` |
| `AccountSummaryUpdate` | `cash`, `buying_power`, `gross_position_value`, `net_liquidation` |

## EventBus (`src/edrader/events/bus.py`)

```python
class EventBus:
    def __init__(self, max_queue_size: int = 10_000,
                 error_handler: ErrorHandler | None = None,
                 subscriber_timeout: float = 5.0) -> None
    def subscribe(self, event_type: type[BaseEvent], handler: AsyncHandler,
                  event_filter: EventFilter | None = None,
                  name: str = "") -> None
    def subscribe_all(self, handler: AsyncHandler,
                      event_filter: EventFilter | None = None,
                      name: str = "") -> None
    def unsubscribe(self, event_type: type[BaseEvent], handler: AsyncHandler) -> None
    async def publish(self, event: BaseEvent) -> None
    async def drain(self) -> None
    async def start(self) -> None
    async def stop(self) -> None
    @property
    def sync_mode(self) -> bool
    @sync_mode.setter
    def sync_mode(self, value: bool) -> None
    @property
    def queue_size(self) -> int
    @property
    def subscriber_count(self) -> int
    def subscriber_count_for(self, event_type: type[BaseEvent]) -> int
    metrics: DispatchMetrics  # total_published, total_dispatched, total_errors, events_by_type, errors_by_type
```

## Strategy (`src/edrader/strategies/base.py`)

```python
class Strategy(ABC):
    def __init__(self, strategy_id: str, event_bus: EventBus) -> None
    @property
    def strategy_id(self) -> str
    @property
    def is_running(self) -> bool

    @abstractmethod
    async def on_event(self, event: BaseEvent) -> None: ...

    async def on_start(self) -> None: ...
    async def on_stop(self) -> None: ...
    async def start(self) -> None
    async def stop(self) -> None

    def event_types(self) -> list[type[BaseEvent]]  # default: [BarCloseEvent]
    async def emit_signal(self, symbol: str, side: str,
                          confidence: float, suggested_size: int) -> None
```

## RiskEngine (`src/edrader/risk/engine.py`)

```python
class RiskEngine:
    def __init__(self, event_bus: EventBus, position_manager: PositionManager,
                 max_position_size: int = 100,
                 max_daily_loss: float = 1000.0, max_leverage: float = 2.0,
                 max_symbol_exposure: float = 50_000.0,
                 max_concurrent_positions: int = 10,
                 stale_market_seconds: float = 300.0) -> None
    async def start(self) -> None
    async def stop(self) -> None
    def activate_kill_switch(self) -> None
    def deactivate_kill_switch(self) -> None
    @property def is_running(self) -> bool
    @property def kill_switch_active(self) -> bool
```

## ExecutionEngine (`src/edrader/execution/engine.py`)

```python
class ExecutionEngine:
    def __init__(self, event_bus: EventBus,
                 sizing_engine: SizingEngine | None = None,
                 default_order_type: str = "MKT",
                 max_retries: int = 3,
                 throttle_delay: float = 0.5) -> None
    async def start(self) -> None
    async def stop(self) -> None
    @property def is_running(self) -> bool
    @property def active_order_count(self) -> int
    @property def active_orders(self) -> dict[str, dict]
```

## SizingEngine (`src/edrader/execution/sizing.py`)

```python
class SizingEngine:
    def __init__(self, method: str = "fixed",
                 percent_equity_fraction: float = 0.02) -> None
    @property def method(self) -> str
    def update_atr(self, symbol: str, atr: float) -> None
    def compute_size(self, suggested_size: int, method: str | None = None,
                     price: float | None = None, equity: float | None = None,
                     symbol: str | None = None) -> int
```

## PositionManager (`src/edrader/portfolio/position.py`)

```python
class PositionManager:
    def __init__(self, event_bus: EventBus, db_manager: Any | None = None,
                 initial_capital: float = 100_000.0,
                 max_symbol_exposure: float | None = None) -> None
    async def start(self) -> None
    async def stop(self) -> None
    async def process_fill(self, event: OrderFilledEvent) -> None
    @property def positions(self) -> dict[str, Position]
    @property def total_realized_pnl(self) -> float
    @property def total_unrealized_pnl(self) -> float
    @property def total_pnl(self) -> float
    @property def equity(self) -> float
    @property def leverage(self) -> float
    def exposure(self) -> ExposureSnapshot
```

## HistoricalFeed (`src/edrader/replay/historical_feed.py`)

```python
class HistoricalFeed:
    def load_csv(self, path: str | Path, symbol: str,
                 time_column: str = "time",
                 open_column: str = "open", high_column: str = "high",
                 low_column: str = "low", close_column: str = "close",
                 volume_column: str = "volume",
                 date_format: str | None = None,
                 start: datetime | None = None,
                 end: datetime | None = None) -> list[BarCloseEvent]
    def load_tick_csv(self, path: str | Path, symbol: str,
                      time_column: str = "time",
                      price_column: str = "price",
                      volume_column: str = "volume",
                      bid_column: str = "bid", ask_column: str = "ask",
                      date_format: str | None = None,
                      start: datetime | None = None,
                      end: datetime | None = None) -> list[MarketTickEvent]
    def filter_by_date(self, start=None, end=None) -> list[BaseEvent]
    def clear(self) -> None
    @property def events(self) -> list[BaseEvent]
    @property def event_count(self) -> int
```

## ReplayEngine (`src/edrader/replay/engine.py`)

```python
class ReplayEngine:
    def __init__(self, event_bus: EventBus, clock: ReplayClock | None = None) -> None
    def load_events(self, events: Sequence[BaseEvent]) -> None
    async def run(self) -> None
    async def step(self) -> bool
    def pause(self) -> None
    def resume(self) -> None
    def stop(self) -> None
    @property def is_running(self) -> bool
    @property def is_paused(self) -> bool
    @property def current_index(self) -> int
    @property def total_events(self) -> int
    @property def clock(self) -> ReplayClock
```

## ReplayClock (`src/edrader/replay/clock.py`)

```python
class ReplayClock:
    def __init__(self, start_time: datetime | None = None) -> None
    def now(self) -> datetime
    def advance(self, seconds: float) -> None
    def set_time(self, dt: datetime) -> None
    def pause(self) -> None
    def resume(self) -> None
    def reset(self) -> None
    @property def speed(self) -> float
    @speed.setter def speed(self, value: float) -> None
    @property def is_paused(self) -> bool
    @property def base_time(self) -> datetime
```

## SimulatedBroker (`src/edrader/replay/simulated_broker.py`)

```python
class SimulatedBroker:
    def __init__(self, event_bus: EventBus, slippage_bps: float = 0.0,
                 commission_per_trade: float = 0.0) -> None
    async def start(self) -> None
    async def stop(self) -> None
    @property def is_running(self) -> bool
    @property def active_order_ids(self) -> list[str]
```

## EventJournal (`src/edrader/events/journal.py`)

```python
class EventJournal:
    def __init__(self, database_url: str, batch_size: int = 1,
                 fast_mode: bool = False) -> None
    async def append(self, event: BaseEvent) -> int
    async def flush(self) -> None
    def close(self) -> None
    async def replay(self, event_types: list[type[BaseEvent]] | None = None,
                     since_sequence: int = 0,
                     limit: int | None = None) -> list[BaseEvent]
    async def count(self) -> int
    @property async def last_sequence(self) -> int
```

## MetricsEngine (`src/edrader/replay/metrics.py`)

```python
class MetricsEngine:
    def __init__(self, event_bus: EventBus, initial_capital: float = 100_000.0,
                 risk_free_rate: float = 0.05) -> None
    async def start(self) -> None
    async def stop(self) -> None
    def compute(self) -> BacktestMetrics

@dataclass
class BacktestMetrics:
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    turnover: float
    start_equity: float
    end_equity: float
    peak_equity: float
```

## MetricsCollector (`src/edrader/monitoring/metrics.py`)

```python
class MetricsCollector:
    def __init__(self, event_bus: EventBus, sample_interval: float = 1.0) -> None
    async def start(self) -> None
    async def stop(self) -> None
    def snapshot(self) -> RuntimeSnapshot
```

## Application (`src/edrader/app/bootstrap.py`)

```python
class Application:
    def __init__(self, config: TradingConfig) -> None
    @classmethod
    def from_config_path(cls, path: Path) -> Application
    async def startup(self) -> None
    async def shutdown(self) -> None
    @property def is_running(self) -> bool
```

## DatabaseManager (`src/edrader/persistence/database.py`)

```python
class DatabaseManager:
    def __init__(self, database_url: str, echo: bool = False) -> None
    def init_db(self) -> None
    def close(self) -> None
    @contextmanager def session(self) -> Generator[Session, None, None]
    @property def is_initialized(self) -> bool
```
