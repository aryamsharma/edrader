# Data Models

## Domain Events (26 types in `src/edrader/events/event_types.py`)

All inherit from `BaseEvent` (frozen dataclass with `slots=True`, `to_dict()`/`from_dict()` serialization).

### Inheritance

```
BaseEvent (event_id, timestamp, priority, correlation_id, source)
├── MarketTickEvent      (symbol, price, volume, bid, ask)
├── BarCloseEvent        (symbol, open, high, low, close, volume)
├── MarketOpenEvent      (symbol)
├── MarketCloseEvent     (symbol)
├── SignalGeneratedEvent (strategy_id, symbol, side, confidence, suggested_size)
├── SignalApprovedEvent  (strategy_id, symbol, side, confidence, suggested_size)
├── SignalRejectedEvent  (strategy_id, symbol, reason)
├── StrategyErrorEvent   (strategy_id, error)
├── RiskViolationEvent   (strategy_id, rule, reason)
├── TradingHaltedEvent   (reason)
├── ExposureLimitEvent   (current_exposure, limit)
├── ExposureUpdatedEvent (gross_exposure, net_exposure, leverage, long_count, short_count, equity)
├── OrderRequestedEvent  (symbol, side, quantity, order_type, limit_price)
├── OrderSubmittedEvent  (order_id, symbol, side, quantity, order_type, limit_price)
├── OrderFilledEvent     (order_id, symbol, side, fill_price, fill_quantity)
├── OrderCancelledEvent  (order_id, reason)
├── OrderStatusChangedEvent (order_id, status)
├── PositionOpenedEvent  (symbol, quantity, avg_cost)
├── PositionClosedEvent  (symbol, realized_pnl)
├── PnLUpdatedEvent      (symbol, unrealized_pnl, realized_pnl)
├── AccountSummaryUpdate (cash, buying_power, gross_position_value, net_liquidation)
├── PositionUpdate       (symbol, position, avg_cost, market_price)
├── BrokerDisconnectedEvent (reason)
├── BrokerReconnectedEvent  (attempts)
├── HeartbeatEvent       (no extra fields)
└── AlertEvent           (alert_type, message, severity)
```

### EventPriority Enum

```python
class EventPriority(Enum):
    LOW = auto()
    NORMAL = auto()
    HIGH = auto()
    CRITICAL = auto()
```

## EventJournal Schema (SQLite)

```sql
CREATE TABLE event_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence INTEGER NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    event_id VARCHAR(64) NOT NULL,
    timestamp DATETIME NOT NULL,
    payload TEXT NOT NULL,
    recorded_at DATETIME NOT NULL
);
CREATE INDEX ix_event_journal_event_id ON event_journal(event_id);
```

## ORM Models (`src/edrader/persistence/models.py`)

4 SQLAlchemy ORM models for long-term storage.

| Model | Table | Key Columns |
|-------|-------|-------------|
| `OrderRecord` | `orders` | id, order_id (unique, indexed), symbol, side, quantity, filled_quantity, order_type, limit_price, status, created_at, updated_at |
| `FillRecord` | `fills` | id, order_id (indexed), symbol, side, fill_price, fill_quantity, fill_time, created_at |
| `PositionRecord` | `positions` | id, symbol (unique, indexed), quantity, avg_cost, updated_at |
| `PnlSnapshotRecord` | `pnl_snapshots` | id, symbol (indexed), unrealized_pnl, realized_pnl, snapshot_time, created_at |

## Configuration Models (`src/edrader/app/config.py`)

Pydantic models loaded from YAML via `load_config(path)` → `TradingConfig`.

```yaml
# Example YAML
app:
  name: trading-platform
  environment: development  # development | paper | live
  log_level: DEBUG
broker:
  host: 127.0.0.1
  port: 4001
  client_id: 1
  connect_timeout: 30
  reconnect_interval: 5.0
  max_reconnect_attempts: 10
risk:
  max_daily_loss: 1000.0
  max_position_size: 100
  max_leverage: 2.0
  max_symbol_exposure: 50000.0
  max_concurrent_positions: 10
execution:
  sizing_method: fixed           # fixed | percent_equity | volatility
  percent_equity_fraction: 0.02
  default_order_type: MKT
  max_retries: 3
  throttle_delay: 0.5
persistence:
  database_url: sqlite:///data/trading.db
  echo: false
monitoring:
  metrics_enabled: true
  metrics_port: 9090
```

## Internal Dataclasses

### Position (`src/edrader/portfolio/position.py`)

```python
@dataclass
class Position:
    symbol: str = ""
    quantity: int = 0
    avg_cost: float = 0.0
    realized_pnl: float = 0.0
```

### ExposureSnapshot (`src/edrader/portfolio/position.py`)

```python
@dataclass
class ExposureSnapshot:
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    long_count: int = 0
    short_count: int = 0
```

### PendingOrder & CompletedOrder (`src/edrader/replay/simulated_broker.py`)

```python
@dataclass
class PendingOrder:
    symbol: str; side: str; quantity: int
    order_type: str; limit_price: float | None; order_id: str

@dataclass
class CompletedOrder:
    order_id: str; symbol: str; side: str
    quantity: int; fill_price: float; commission: float = 0.0
```

### BacktestMetrics (`src/edrader/replay/metrics.py`)

```python
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
```

### RuntimeSnapshot (`src/edrader/monitoring/metrics.py`)

```python
@dataclass
class RuntimeSnapshot:
    queue_depth: int = 0
    subscriber_count: int = 0
    throughput_1m: float = 0.0
    total_published: int = 0
    total_dispatched: int = 0
    total_errors: int = 0
    top_event_types: list[tuple[str, int]] = field(default_factory=list)
    top_error_types: list[tuple[str, int]] = field(default_factory=list)
```

### SubscriberEntry (`src/edrader/events/bus.py`)

```python
class SubscriberEntry:
    handler: AsyncHandler
    event_filter: EventFilter | None
    name: str
```

### DispatchMetrics (`src/edrader/events/bus.py`)

```python
class DispatchMetrics:
    total_published: int = 0
    total_dispatched: int = 0
    total_errors: int = 0
    events_by_type: dict[str, int]
    errors_by_type: dict[str, int]
    def snapshot(self) -> dict[str, Any]: ...
```
