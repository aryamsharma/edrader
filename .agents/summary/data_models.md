# Data Models

## Event Models (`events/event_types.py`)

### BaseEvent
```python
@dataclass(frozen=True, slots=True)
class BaseEvent:
    event_id: str          # uuid4 hex (16 chars)
    timestamp: datetime    # UTC
    priority: EventPriority  # LOW, NORMAL, HIGH, CRITICAL
    correlation_id: str    # For tracing related events
    source: str            # Component that created this event
```

All 27 concrete event types extend `BaseEvent` with domain-specific fields (see `interfaces.md` for full catalog).

### EventPriority Enum
```python
class EventPriority(Enum):
    LOW = auto()
    NORMAL = auto()
    HIGH = auto()
    CRITICAL = auto()
```

## Domain Dataclasses

### Position (`portfolio/position.py`)
```python
@dataclass
class Position:
    symbol: str
    quantity: int            # Positive=long, Negative=short
    avg_cost: float          # Average entry price
    realized_pnl: float      # Cumulative realized PnL
```

### ExposureSnapshot (`portfolio/position.py`)
```python
@dataclass
class ExposureSnapshot:
    gross_exposure: float    # Sum of |position| * price
    net_exposure: float      # Long - short exposure
    long_count: int          # Number of long positions
    short_count: int         # Number of short positions
```

### BacktestMetrics (`replay/metrics.py`)
```python
@dataclass
class BacktestMetrics:
    total_return: float      # (end - start) / start
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float      # Peak-to-trough percentage
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    turnover: float          # Total traded / avg equity
    start_equity: float
    end_equity: float
    peak_equity: float
```

### PendingOrder / CompletedOrder (`replay/simulated_broker.py`)
```python
@dataclass
class PendingOrder:
    symbol: str
    side: str                # BUY / SELL
    quantity: int
    order_type: str          # MKT / LMT
    limit_price: float | None
    order_id: str

@dataclass
class CompletedOrder:
    order_id: str
    symbol: str
    side: str
    quantity: int
    fill_price: float
    commission: float
```

### RuntimeSnapshot (`monitoring/metrics.py`)
```python
@dataclass
class RuntimeSnapshot:
    queue_depth: int
    subscriber_count: int
    throughput_1m: float
    total_published: int
    total_dispatched: int
    total_errors: int
    top_event_types: list[tuple[str, int]]
    top_error_types: list[tuple[str, int]]
```

### DispatchMetrics (`events/bus.py`)
```python
class DispatchMetrics:
    total_published: int
    total_dispatched: int
    total_errors: int
    events_by_type: dict[str, int]
    errors_by_type: dict[str, int]
```

## Database Models (`persistence/models.py`)

All ORM models use SQLAlchemy `DeclarativeBase`:

### OrderRecord (`orders` table)
| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| order_id | String(64) | NOT NULL, UNIQUE, indexed |
| symbol | String(32) | NOT NULL |
| side | String(8) | NOT NULL |
| quantity | Integer | NOT NULL |
| filled_quantity | Integer | NOT NULL, default 0 |
| order_type | String(16) | NOT NULL |
| limit_price | Float | NULLABLE |
| status | String(32) | NOT NULL, default 'PendingSubmit' |
| created_at | DateTime(tz) | NOT NULL |
| updated_at | DateTime(tz) | NOT NULL |

### FillRecord (`fills` table)
| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| order_id | String(64) | NOT NULL, indexed |
| symbol | String(32) | NOT NULL |
| side | String(8) | NOT NULL |
| fill_price | Float | NOT NULL |
| fill_quantity | Integer | NOT NULL |
| fill_time | DateTime(tz) | NOT NULL |
| created_at | DateTime(tz) | NOT NULL |

### PositionRecord (`positions` table)
| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| symbol | String(32) | NOT NULL, UNIQUE, indexed |
| quantity | Integer | NOT NULL |
| avg_cost | Float | NOT NULL |
| updated_at | DateTime(tz) | NOT NULL |

### PnlSnapshotRecord (`pnl_snapshots` table)
| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| symbol | String(32) | NOT NULL, indexed |
| unrealized_pnl | Float | NOT NULL |
| realized_pnl | Float | NOT NULL |
| snapshot_time | DateTime(tz) | NOT NULL |
| created_at | DateTime(tz) | NOT NULL |

### EventRecord (`event_journal` table, from `events/journal.py`)
| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| sequence | Integer | NOT NULL, monotonic |
| event_type | String(128) | NOT NULL |
| event_id | String(64) | NOT NULL, indexed |
| timestamp | DateTime(tz) | NOT NULL |
| payload | Text | NOT NULL (JSON string) |
| recorded_at | DateTime(tz) | NOT NULL |

## Config Models (`app/config.py`)

```python
class TradingConfig(BaseModel):
    app: AppConfig           # name, environment, log_level
    broker: BrokerConfig     # host, port, reconnect params
    risk: RiskConfig         # max_daily_loss, max_position_size, etc.
    persistence: PersistenceConfig  # database_url, echo
    monitoring: MonitoringConfig    # metrics_enabled, metrics_port
    execution: ExecutionConfig      # sizing_method, throttle_delay, etc.
```

## Serialization

Events serialize via `to_dict()` / `from_dict()`:

```python
# Serialize
event = MarketTickEvent(symbol="AAPL", price=150.0)
data = event.to_dict()
# {
#   "event_type": "MarketTickEvent",
#   "event_id": "a1b2c3d4e5f6g7h8",
#   "timestamp": "2026-05-27T...",
#   "priority": "NORMAL",
#   "correlation_id": "",
#   "source": "",
#   "symbol": "AAPL",
#   "price": 150.0,
#   "volume": 0,
#   "bid": 0.0,
#   "ask": 0.0
# }

# Deserialize
restored = BaseEvent.from_dict(data)
```

- Enum values serialized as `.name` (string)
- Timestamps serialized as ISO format, restored via `fromisoformat`
- Unknown event_type falls back to `BaseEvent`
- Custom `to_dict` uses `default=str` for non-serializable fields (e.g., `datetime` in some nested cases)
