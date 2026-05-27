# Components

## 1. Event System (`events/`)

### EventBus (`events/bus.py`)
- **File:** `src/trading_platform/events/bus.py`
- **Purpose:** Central async pub/sub with typed subscriptions and priority queues
- **Subscribes to:** Nothing (publishes via `publish()`)
- **Publishes:** Nothing directly (other components publish through it)
- **Key features:** Dual priority queues, typed subscriptions, wildcard subscribe_all, predicate filters, error handlers, metrics tracking, `drain()` for test synchronization
- **Lifecycle:** `start()`, `stop()`, idempotent

### Event Types (`events/event_types.py`)
- **File:** `src/trading_platform/events/event_types.py`
- **Purpose:** 27 frozen dataclass event types inheriting `BaseEvent`
- **Serialization:** `to_dict()` / `from_dict()` with ISO timestamps and enum name serialization

### EventJournal (`events/journal.py`)
- **File:** `src/trading_platform/events/journal.py`
- **Purpose:** SQLite append-only event store for replay and audit
- **Methods:** `append()`, `replay()` (with type/since/limit filters), `count()`, `close()`

## 2. Broker Integration (`broker/`)

### IBKRClient (`broker/ibkr_client.py`)
- **File:** `src/trading_platform/broker/ibkr_client.py`
- **Purpose:** Connection lifecycle to IB Gateway/TWS with auto-reconnect
- **Subscribes to:** Nothing
- **Publishes:** `BrokerReconnectedEvent`, `BrokerDisconnectedEvent`, `HeartbeatEvent`
- **Key features:** Reconnect loop with max attempt limit, heartbeat monitoring, disconnect handler

### MarketDataFeed (`broker/market_data.py`)
- **File:** `src/trading_platform/broker/market_data.py`
- **Purpose:** Manages IBKR tick subscriptions, aggregates bars from ticks
- **Subscribes to:** `BrokerReconnectedEvent` (auto re-subscribe on reconnect)
- **Publishes:** `MarketTickEvent`, `BarCloseEvent`
- **Key features:** Per-symbol BarAggregator, tick→bar conversion, auto re-subscribe on reconnect

### BrokerAdapter (`broker/order_management.py`)
- **File:** `src/trading_platform/broker/order_management.py`
- **Purpose:** Places/cancels orders via IBKR, tracks order status and fills
- **Subscribes to:** `OrderRequestedEvent`
- **Publishes:** `OrderSubmittedEvent`, `OrderFilledEvent`, `OrderStatusChangedEvent`, `OrderCancelledEvent`

## 3. Portfolio (`portfolio/`)

### PositionManager (`portfolio/position.py`)
- **File:** `src/trading_platform/portfolio/position.py`
- **Purpose:** Tracks positions with avg cost, realized/unrealized PnL, exposure, leverage
- **Subscribes to:** `OrderFilledEvent`, `MarketTickEvent`
- **Publishes:** `PositionOpenedEvent`, `PositionClosedEvent`, `PnLUpdatedEvent`, `PositionUpdate`, `ExposureUpdatedEvent`, `ExposureLimitEvent`
- **Key features:** Multi-symbol support, short/long handling, tick-based mark-to-market, exposure snapshots, optional DB persistence

## 4. Risk (`risk/`)

### RiskEngine (`risk/engine.py`)
- **File:** `src/trading_platform/risk/engine.py`
- **Purpose:** Validates signals against configurable risk rules
- **Subscribes to:** `SignalGeneratedEvent`, `OrderFilledEvent`, `MarketTickEvent`, `BrokerDisconnectedEvent`, `ExposureUpdatedEvent`
- **Publishes:** `SignalApprovedEvent`, `SignalRejectedEvent`, `RiskViolationEvent`, `TradingHaltedEvent`
- **Risk checks:**
  1. Max position size (`max_position_size`)
  2. Max daily loss (`max_daily_loss`, allows reducing positions)
  3. Max leverage (`max_leverage`)
  4. Max symbol exposure (`max_symbol_exposure`)
  5. Max concurrent positions (`max_concurrent_positions`)
  6. Stale market data (`stale_market_seconds`)
- **Other features:** Kill switch (activated by disconnect), exposure auto-update via `ExposureUpdatedEvent`

## 5. Execution (`execution/`)

### ExecutionEngine (`execution/engine.py`)
- **File:** `src/trading_platform/execution/engine.py`
- **Purpose:** Converts approved signals to order requests with throttling and sizing
- **Subscribes to:** `SignalApprovedEvent`, `MarketTickEvent`, `OrderSubmittedEvent`
- **Publishes:** `OrderRequestedEvent`, `OrderSubmittedEvent` (throttle notification)
- **Key features:** Per-symbol throttle, configurable sizing via `SizingEngine`, price caching from ticks

### SizingEngine (`execution/sizing.py`)
- **File:** `src/trading_platform/execution/sizing.py`
- **Purpose:** Computes order size based on method (fixed, percent_equity, volatility)
- **Methods:** `compute_size(suggested_size, method, price, equity)`
- **Default method:** `"fixed"` (returns suggested_size as-is)

## 6. Replay/Backtesting (`replay/`)

### ReplayClock (`replay/clock.py`)
- **File:** `src/trading_platform/replay/clock.py`
- **Purpose:** Simulated clock that can be sped up, paused, and reset
- **Key features:** Speed multiplier, pause/resume, time advancement

### ReplayEngine (`replay/engine.py`)
- **File:** `src/trading_platform/replay/engine.py`
- **Purpose:** Publishes pre-loaded events in chronological order
- **Key features:** `step()` (single event), `run()` (all events), pause/resume, sorted by timestamp

### HistoricalFeed (`replay/historical_feed.py`)
- **File:** `src/trading_platform/replay/historical_feed.py`
- **Purpose:** Loads CSV data into `BarCloseEvent` lists
- **Key features:** Column mapping, date filtering, malformed row skipping, custom date formats

### SimulatedBroker (`replay/simulated_broker.py`)
- **File:** `src/trading_platform/replay/simulated_broker.py`
- **Purpose:** Simulates order execution for backtesting
- **Subscribes to:** `OrderRequestedEvent`, `BarCloseEvent`, `MarketTickEvent`
- **Publishes:** `OrderSubmittedEvent`, `OrderFilledEvent`, `OrderStatusChangedEvent`
- **Key features:** Market/limit order fills, slippage, commissions, deferred fills (price arrives after order), held market orders

### MetricsEngine (`replay/metrics.py`)
- **File:** `src/trading_platform/replay/metrics.py`
- **Purpose:** Computes backtest performance metrics
- **Subscribes to:** `ExposureUpdatedEvent`, `OrderFilledEvent`, `PositionClosedEvent`
- **Publishes:** Nothing directly
- **Key metrics:** Total/annualized return, Sharpe ratio, max drawdown, win rate, turnover, equity summary

## 7. Monitoring (`monitoring/`)

### MetricsCollector (`monitoring/metrics.py`)
- **File:** `src/trading_platform/monitoring/metrics.py`
- **Purpose:** Samples EventBus dispatch metrics at configurable intervals
- **Key features:** Throughput computation (events/sec over 60s window), `RuntimeSnapshot` dataclass with queue depth, subscriber count, top event types

### AlertManager (`monitoring/alerts.py`)
- **File:** `src/trading_platform/monitoring/alerts.py`
- **Purpose:** Monitors events and publishes `AlertEvent` with cooldown deduplication
- **Subscribes to:** `BrokerDisconnectedEvent`, `BrokerReconnectedEvent`, `RiskViolationEvent`, `SignalRejectedEvent`, `TradingHaltedEvent`, `HeartbeatEvent`
- **Publishes:** `AlertEvent`
- **Key features:** Cooldown per alert_type, heartbeat health monitoring, severity levels

### Logging (`monitoring/logging.py`)
- **File:** `src/trading_platform/monitoring/logging.py`
- **Purpose:** Structured logging with structlog
- **Key features:** Context vars, console/JSON renderer based on TTY, filtering bound loggers

## 8. Strategies (`strategies/`)

### Strategy Base (`strategies/base.py`)
- **File:** `src/trading_platform/strategies/base.py`
- **Purpose:** Abstract base class for all trading strategies
- **Key features:** `emit_signal()` helper, lifecycle (start/stop), auto-subscribe to event types
- **Constraint:** Strategies emit signals only — no orders, no positions, no IBKR calls

### StrategyLoader (`strategies/base.py`)
- **File:** `src/trading_platform/strategies/base.py`
- **Purpose:** Registry for creating strategy instances by ID
- **Key features:** Register/create pattern, duplicate detection

### SmaCrossoverStrategy (`strategies/examples/sma_crossover.py`)
- **File:** `src/trading_platform/strategies/examples/sma_crossover.py`
- **Purpose:** Simple moving average crossover strategy (BUY on fast>slow, SELL on fast<slow)
- **Parameters:** fast_window (10), slow_window (30), default_size (100)

### MeanReversionStrategy (`strategies/examples/mean_reversion.py`)
- **File:** `src/trading_platform/strategies/examples/mean_reversion.py`
- **Purpose:** Z-score mean reversion strategy
- **Parameters:** window (20), entry_z (2.0), exit_z (0.5), default_size (100)

## 9. Persistence (`persistence/`)

### DatabaseManager (`persistence/database.py`)
- **File:** `src/trading_platform/persistence/database.py`
- **Purpose:** Centralized SQLAlchemy engine and session lifecycle
- **Key features:** init_db (creates all tables), close, contextmanager session with auto commit/rollback

### Domain Models (`persistence/models.py`)
- **File:** `src/trading_platform/persistence/models.py`
- **Models:** `OrderRecord`, `FillRecord`, `PositionRecord`, `PnlSnapshotRecord`

## 10. Application Bootstrapping (`app/`)

### Application (`app/bootstrap.py`)
- **File:** `src/trading_platform/app/bootstrap.py`
- **Purpose:** Wires config, EventBus, and lifecycle
- **Key features:** `from_config_path()`, `startup()`, `shutdown()`

### Config (`app/config.py`)
- **File:** `src/trading_platform/app/config.py`
- **Purpose:** pydantic-based configuration with YAML loading
- **Sub-configs:** `AppConfig`, `BrokerConfig`, `RiskConfig`, `PersistenceConfig`, `MonitoringConfig`, `ExecutionConfig`

### Main Entry (`app/main.py`)
- **File:** `src/trading_platform/app/main.py`
- **Purpose:** Signal-handled asyncio entry point
