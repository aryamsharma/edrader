# Major Components

## 1. EventBus (`events/bus.py`)

Central message broker. All module communication flows through this component.

- **PriorityQueue**: Dual `asyncio.Queue` — high-priority events always processed first
- **Subscriber management**: Typed `subscribe()`, wildcard `subscribe_all()`, optional predicate filters
- **DispatchMetrics**: Tracks published/dispatched/error counts by event type
- **Error handling**: Configurable error handler callback, exception isolation per subscriber
- **Lifecycle**: `start()`/`stop()` with background `_process_events` task

## 2. EventJournal (`events/journal.py`)

Append-only SQLite store for event persistence and replay.

- **EventRecord**: SQLAlchemy model with sequence, event_type, event_id, timestamp, payload (JSON)
- **append()**: Writes event to journal, returns sequence number
- **replay()**: Reads events with optional type filter, sequence offset, limit
- **count()/last_sequence**: Journal state queries

## 3. BaseEvent & Event Types (`events/event_types.py`)

25 frozen dataclass event types + base.

| Category | Events |
|---|---|
| Market | MarketTickEvent, BarCloseEvent, MarketOpenEvent, MarketCloseEvent |
| Strategy | SignalGeneratedEvent, SignalRejectedEvent, StrategyErrorEvent |
| Risk | RiskViolationEvent, TradingHaltedEvent, ExposureLimitEvent |
| Order | OrderRequestedEvent, OrderSubmittedEvent, OrderFilledEvent, OrderCancelledEvent, OrderStatusChangedEvent |
| Position | PositionOpenedEvent, PositionClosedEvent, PnLUpdatedEvent |
| Account | AccountSummaryUpdate, PositionUpdate |
| Broker | BrokerDisconnectedEvent, BrokerReconnectedEvent |
| System | HeartbeatEvent |

## 4. IBKRClient (`broker/ibkr_client.py`)

IBKR connection lifecycle manager.

- **connect()**: Async connection via `ib.connectAsync()`, sets up disconnect handler, starts heartbeat
- **disconnect()**: Cancels tasks, removes handlers, disconnects IB
- **Reconnect loop**: Exponential backoff with configurable max attempts; publishes `BrokerDisconnectedEvent`/`BrokerReconnectedEvent`
- **Heartbeat**: Periodic `HeartbeatEvent` publication, detects connection loss
- **Testable**: Constructor accepts mock `ib` object

## 5. MarketDataFeed (`broker/market_data.py`)

IBKR market data subscription manager.

- **subscribe_symbol()**: Requests market data via `ib.reqMktData()`, creates `BarAggregator`
- **unsubscribe()/unsubscribe_all()**: Cancels market data subscriptions
- **Tick processing**: Listens on `pendingTickersEvent`, publishes `MarketTickEvent`, aggregates bars
- **BarAggregator**: Time-windowed OHLCV from `MarketTickEvent` → `BarCloseEvent`
- **Auto re-subscribe**: Listens for `BrokerReconnectedEvent`, re-requests all subscriptions
- **Lifecycle**: `start()`/`stop()` with clean handler disconnect

## 6. Application (`app/bootstrap.py`)

Top-level orchestrator.

- Holds `TradingConfig` and `EventBus`
- `from_config_path()`: Factory method loading YAML config
- `startup()`: Starts event bus, initializes components
- `shutdown()`: Stops event bus gracefully

## 7. Configuration (`app/config.py`)

Pydantic model hierarchy for YAML-based configuration.

- **TradingConfig**: Composite of AppConfig, BrokerConfig, RiskConfig, PersistenceConfig, MonitoringConfig
- **load_config()**: Loads and validates YAML, returns typed config object

## 8. Stub Modules (6 empty directories)

Planned but not yet implemented:

| Module | Responsibility |
|---|---|
| `execution/` | Order lifecycle, signal→order conversion, retry, throttling |
| `persistence/` | Database engine, SQLAlchemy models, repositories |
| `portfolio/` | Position tracking, PnL, exposure calculations |
| `replay/` | Historical data feed, replay clock, simulated broker |
| `risk/` | Signal validation, position sizing limits, kill switch |
| `strategies/` | Strategy base class, loader, example implementations |

## Test Patterns

- **pytest-asyncio** with `asyncio_mode = auto`
- Class-based grouping (e.g., `TestIBKRClientConnect`)
- `MagicMock`/`AsyncMock` for broker/client injection
- `collected_events` fixture for event assertion via `subscribe_all`
- `await event_bus.drain()` before asserting published events
- `tmp_path` for SQLite journal tests
