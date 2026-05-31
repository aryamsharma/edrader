# Components

## EventBus (`src/edrader/events/bus.py`)

Central message broker. All inter-component communication flows through the EventBus as typed domain events.

- **PriorityQueue**: dual `asyncio.Queue` (high/critical vs normal/low priority)
  - `get()`: `get_nowait()` on high then normal; `wait_for(high.get(), 0.001)`; finally blocking `normal.get()`
  - `task_done()` delegates to `_last_source` queue
  - `qsize()`, `high_size`, `normal_size`, `join()`
- **Subscription model**: `subscribe(event_type, handler, event_filter, name)` returns unsubscribe callable; `subscribe_all(handler, event_filter, name)` for wildcard
- **Handler cache**: `_handler_cache` dict keyed by event type, rebuilt on subscribe/unsubscribe via `_invalidate_cache()`
- **Dispatch**: `publish(event)` is async; in `sync_mode` calls `_dispatch()` directly, otherwise enqueues to PriorityQueue
- **Dispatch processing**: `_dispatch()` iterates handlers with `asyncio.wait_for(timeout=subscriber_timeout)` catching TimeoutError and Exception
- **Sync mode**: `EventBus.sync_mode` property (get/set); when True, `publish()` dispatches subscribers synchronously within the call; used by ReplayEngine during `run()`
- **Metrics**: `DispatchMetrics` tracks `total_published`, `total_dispatched`, `total_errors`, `events_by_type`, `errors_by_type`
- **Lifecycle**: `start()` creates `_processing_task`; `stop()` cancels task; `drain()` awaits `_queue.join()`

## EventJournal (`src/edrader/events/journal.py`)

Append-only SQLite event store for replay and audit.

- **Constructor**: `EventJournal(database_url, batch_size=1, fast_mode=False)`
  - `fast_mode=True` sets `PRAGMA synchronous=OFF, journal_mode=MEMORY, cache_size=-64000`
  - Creates `event_journal` table via ORM metadata
- **Writing**: `append(event)` serializes via `event.to_dict()` + `json.dumps()`, buffers in `_buffer` list; auto-flushes when `len(buffer) >= batch_size`
  - Async via `asyncio.to_thread()` for SQLite writes
- **Flushing**: `flush()` writes buffered events via raw SQL `executemany`; `close()` does final flush + `engine.dispose()`
- **Reading**: `replay(event_types, since_sequence, limit)` queries with optional type filter (by class name) and sequence offset
- **Sequence tracking**: `_sequence` counter incremented per append; resumed from DB max on first call to `_ensure_sequence()`
- **Schema**: `event_journal(id PK, sequence INT, event_type STR, event_id STR, timestamp DT, payload TEXT, recorded_at DT)`
- **Concurrency**: `asyncio.Lock` protects `_buffer` access

## RiskEngine (`src/edrader/risk/engine.py`)

Validates signals before execution. 6 configurable checks plus kill switch.

- **Constructor params**: `max_position_size` (100), `max_daily_loss` (1000.0), `max_leverage` (2.0), `max_symbol_exposure` (50000.0), `max_concurrent_positions` (10), `stale_market_seconds` (300.0)
- **Checks** (all run per signal):
  1. `max_position_size`: suggested_size > limit
  2. `max_daily_loss`: abs(realized_pnl) >= limit (only for position-increasing signals)
  3. `max_leverage`: gross_exposure / equity >= limit
  4. `max_symbol_exposure`: currently returns None (not implemented)
  5. `max_concurrent_positions`: non-zero positions >= limit (only for new symbols)
  6. `stale_market`: seconds since last tick > limit
- **Kill switch**: `activate_kill_switch()` / `deactivate_kill_switch()`; auto-activated on `BrokerDisconnectedEvent` + publishes `TradingHaltedEvent`
- **State tracking**: positions (from fills), last tick time per symbol, exposure/equity (from ExposureUpdatedEvent), daily realized P&L
- **Output**: publishes `SignalApprovedEvent` or `SignalRejectedEvent`; publishes `RiskViolationEvent` on each rejection
- **Subscriptions**: SignalGeneratedEvent, OrderFilledEvent, MarketTickEvent, BrokerDisconnectedEvent, ExposureUpdatedEvent

## ExecutionEngine (`src/edrader/execution/engine.py`)

Converts approved signals into orders.

- **Constructor params**: `sizing_engine`, `default_order_type` ("MKT"), `max_retries` (3), `throttle_delay` (0.5)
- **Flow**: receives `SignalApprovedEvent` → throttle check → `SizingEngine.compute_size()` → publish `OrderRequestedEvent`
- **Throttle**: per-symbol cooldown via `time.monotonic()`; if throttled, publishes empty `OrderSubmittedEvent` as no-op
- **Retry**: background task re-publishes `OrderRequestedEvent` after 2s if no `OrderSubmittedEvent` with order_id received; up to `max_retries` times
- **Price tracking**: updates `_prices[symbol]` from `MarketTickEvent`
- **Order tracking**: `_active_orders` dict keyed by order_id; removed on fill or cancel
- **Equity tracking**: updated from `ExposureUpdatedEvent.equity`
- **Subscriptions**: SignalApprovedEvent, MarketTickEvent, OrderSubmittedEvent, OrderFilledEvent, OrderCancelledEvent, ExposureUpdatedEvent

## SizingEngine (`src/edrader/execution/sizing.py`)

Computes order quantities.

- **Constructor**: `method` ("fixed"), `percent_equity_fraction` (0.02)
- **Methods**: `compute_size(suggested_size, method, price, equity, symbol)` → int
  - `"fixed"` (default): returns `suggested_size` as-is
  - `"percent_equity"`: `int(equity * fraction / price)`
  - `"volatility"`: uses ATR cache; `int(risk_amount / atr)` or `int(suggested_size / atr_pct)`
- **ATR cache**: `update_atr(symbol, atr)` for volatility sizing

## PositionManager (`src/edrader/portfolio/position.py`)

Tracks positions, exposures, and P&L per instrument.

- **Constructor**: `event_bus`, `db_manager` (optional), `initial_capital` (100_000.0), `max_symbol_exposure` (optional)
- **Position tracking**: `_positions[symbol] = Position(quantity, avg_cost, realized_pnl)`
- **Fill processing `process_fill()`**:
  - Updates quantity/avg_cost with weighted average for same-direction fills
  - Computes realized P&L for reducing/covering fills
  - Publishes `PositionOpenedEvent` (new position), `PositionClosedEvent` (flat), `PnLUpdatedEvent`
  - Persists via `_db_manager` if configured
  - Publishes `ExposureUpdatedEvent` (gross/net exposure, leverage, long/short counts, equity)
  - Publishes `ExposureLimitEvent` if `max_symbol_exposure` exceeded
- **Tick processing**: updates `_market_prices` from `MarketTickEvent`; publishes `PnLUpdatedEvent`, `PositionUpdate`, and `ExposureUpdatedEvent` on price changes for active positions
- **Properties**: `positions`, `total_realized_pnl`, `total_unrealized_pnl`, `total_pnl`, `equity`, `leverage`, `exposure()` → `ExposureSnapshot`

## MarketDataFeed (`src/edrader/broker/market_data.py`)

Live market data from IBKR.

- Connects to IBKR via `ib_async`; requests market data for configured contracts
- Publishes `MarketTickEvent` (HIGH priority) and `BarCloseEvent`
- Bar aggregation is tick-triggered: emitted when a tick arrives after the time window

## BrokerAdapter (`src/edrader/broker/order_management.py`)

Live order execution via IBKR.

- Subscribes to `OrderRequestedEvent`; places orders via `ib_async`
- Tracks fills; publishes `OrderSubmittedEvent`, `OrderStatusChangedEvent`, `OrderFilledEvent`, `OrderCancelledEvent`

## IBKRClient (`src/edrader/broker/ibkr_client.py`)

Low-level IBKR connection manager.

- `ib_async.IB()` typed as `Any` (no stubs) — `# type: ignore[no-untyped-call]` on constructor
- Async connect/disconnect with configurable host/port/client_id, timeout, reconnect_interval
- `is_connected()` health check; `ensure_connection()` with retry; publishes `BrokerDisconnectedEvent`/`BrokerReconnectedEvent`

## SimulatedBroker (`src/edrader/replay/simulated_broker.py`)

Backtest order execution.

- **Constructor**: `event_bus`, `slippage_bps` (0.0), `commission_per_trade` (0.0)
- **Flow**: receives `OrderRequestedEvent` → creates `PendingOrder`
  - MKT orders: fill immediately at current price; if no price available, add to `_held_market_orders`
  - LMT orders: if limit price crossed by current price, fill; otherwise add to `_pending_orders`
- **Fill execution**: 3 events per fill — `OrderSubmittedEvent` → `OrderStatusChangedEvent(Filled)` → `OrderFilledEvent`
- **Price updates**: from `BarCloseEvent.close` and `MarketTickEvent.price`; pending/held orders checked on each price update
- **Slippage**: `slippage_bps / 10000 * price` — added for BUY, subtracted for SELL
- **Commission**: flat `commission_per_trade` added to `CompletedOrder`
- **Data types**: `PendingOrder` and `CompletedOrder` dataclasses

## HistoricalFeed (`src/edrader/replay/historical_feed.py`)

Loads CSV data for backtesting.

- **`load_csv(path, symbol, time_column, open/high/low/close/volume_column, date_format, start, end)`**: parses OHLCV CSV → `list[BarCloseEvent]`, sorted by timestamp
- **`load_tick_csv(path, symbol, time_column, price/volume/bid/ask_column, date_format, start, end)`**: parses tick CSV → `list[MarketTickEvent]`, sorted by timestamp
- **`filter_by_date(start, end)`**: filter loaded events by datetime range
- **`clear()`**: reset events list
- Properties: `events`, `event_count`
- All time parsing: tries `date_format` via `strptime` or falls back to `datetime.fromisoformat`; always sets `tzinfo=UTC`

## ReplayEngine (`src/edrader/replay/engine.py`)

Drives backtest event publishing.

- **Constructor**: `event_bus`, `clock` (default ReplayClock)
- **`load_events(events)`**: stable-sorts by `e.timestamp`; sets clock start time to first event
- **`run()`**: enables `sync_mode`; iterates events calling `_publish_event()` then `_wait_for_next()`; disables sync_mode in `finally`
  - `_publish_event(event)`: `clock.set_time(event.timestamp)` then `event_bus.publish(event)`
  - `_wait_for_next(current, next)`: computes `delta = (next.timestamp - current.timestamp) / speed`; skips if <= 0; skips if adjusted < 1ms; sleeps in 0.1s chunks
- **`step()`**: publish single event, advance index; used for debugging
- **`pause()`/`resume()`**: set `_paused` flag; sleep 0.1s in run loop while paused
- **`stop()`**: sets `_running = False`, run loop exits

## ReplayClock (`src/edrader/replay/clock.py`)

Time simulation for backtesting.

- **State**: `_base_time`, `_elapsed` (seconds), `_speed` (multiplier), `_paused`
- **`now()`**: returns `_base_time + elapsed * speed`; if paused, returns `_base_time`
- **`set_time(dt)`**: resets `_elapsed = 0`, sets `_base_time = dt`
- **`advance(seconds)`**: increments `_elapsed` (no-op if paused)
- **`pause()`/`resume()`**: pause freezes time; resume recalculates `_base_time` from paused state
- **`reset()`**: clears elapsed and sets speed to 1.0
- No `wait_until()` — caller is responsible for pacing (ReplayEngine._wait_for_next)

## Strategies (`src/edrader/strategies/`)

### Base Classes

- **`Strategy`** (ABC): `__init__(strategy_id, event_bus)`, abstract `on_event(event)`, lifecycle hooks `on_start()`/`on_stop()`, `event_types()` returns subscribed types (default `[BarCloseEvent]`), `emit_signal()` publishes `SignalGeneratedEvent`
- **`StrategyLoader`**: registry with `register(id, class)` and `create(id, event_bus, **kwargs)`

### Built-in Strategies

- **`SmaCrossoverStrategy`**: BarCloseEvent subscriber; configurable fast_window (10) / slow_window (30); `_prices` deque per symbol; BUY on fast SMA crossing above slow, SELL on crossing below; fixed `default_size` (100)
- **`MeanReversionStrategy`**: BarCloseEvent subscriber; configurable window (20), entry_z (2.0), exit_z (0.5); tracks position_side per symbol; BUY when z <= -entry_z, SELL when z >= entry_z; exit when |z| <= exit_z
- **`VwapReversionStrategy`**: MarketTickEvent subscriber; configurable window (100), entry_pct (0.01), exit_pct (0.002); rolling VWAP with cumulative sum optimization; SELL when deviation > entry_pct, BUY when deviation < -entry_pct; exit when |deviation| < exit_pct

## MetricsEngine (`src/edrader/replay/metrics.py`)

Backtest performance computation.

- **Constructor**: `event_bus`, `initial_capital` (100_000.0), `risk_free_rate` (0.05)
- **Data collection**: subscribes to ExposureUpdatedEvent (equity curve), OrderFilledEvent (traded value), PositionClosedEvent (win/loss)
- **`compute()`** → `BacktestMetrics`: total_return, annualized_return, sharpe_ratio, max_drawdown, win_rate, total_trades, winning_trades, losing_trades, turnover, start_equity, end_equity, peak_equity

## MetricsCollector (`src/edrader/monitoring/metrics.py`)

Live runtime monitoring.

- **Constructor**: `event_bus`, `sample_interval` (1.0)
- **Data collection**: `subscribe_all` handler counts events by type; periodic sampling loop for throughput computation
- **`snapshot()`** → `RuntimeSnapshot`: queue_depth, subscriber_count, throughput_1m, total_published/dispatched/errors, top event/error types

## AlertManager (`src/edrader/monitoring/alerts.py`)

Alert generation for system events.

- **Constructor**: `event_bus`, `cooldown_seconds` (60.0), `heartbeat_timeout` (30.0)
- **Subscriptions**: BrokerDisconnectedEvent, BrokerReconnectedEvent, RiskViolationEvent, SignalRejectedEvent, TradingHaltedEvent, HeartbeatEvent
- **Alert types**: broker_disconnected (CRITICAL), broker_reconnected (INFO), risk_violation (ERROR), signal_rejected (WARNING), trading_halted (CRITICAL), heartbeat_missed (ERROR)
- **Cooldown**: per-alert-type cooldown prevents alert storms; heartbeat check loop runs every `heartbeat_timeout / 2` seconds

## Application (`src/edrader/app/bootstrap.py`)

Wires all components for live or simulated mode.

- **`startup()`**: starts EventBus; builds and starts component groups based on environment (development→simulated, paper/live→IBKR); wires journal as subscribe_all; registers + starts strategies
- **`shutdown()`**: stops strategies, component groups (in reverse order), closes journal, stops EventBus
- **Component groups**: `LIVE_COMPONENTS` (IBKRClient, MarketDataFeed, BrokerAdapter), `SIMULATED_COMPONENTS` (SimulatedBroker), `MONITORING_COMPONENTS` (RiskEngine, ExecutionEngine, PositionManager, MetricsCollector, AlertManager)

## Config (`src/edrader/app/config.py`)

Pydantic configuration hierarchy, loaded from YAML.

- `BrokerConfig`: host, port, client_id, connect_timeout, reconnect_interval, max_reconnect_attempts
- `RiskConfig`: max_daily_loss, max_position_size, max_leverage, max_symbol_exposure, max_concurrent_positions
- `ExecutionConfig`: sizing_method, percent_equity_fraction, default_order_type, max_retries, throttle_delay
- `PersistenceConfig`: database_url, echo
- `MonitoringConfig`: metrics_enabled, metrics_port
- `AppConfig`: name, environment (development/paper/live), log_level
- `TradingConfig`: wraps all above with defaults

## Persistence (`src/edrader/persistence/`)

- **`DatabaseManager`**: sync SQLAlchemy engine; `init_db()` creates tables; `session()` context manager with commit/rollback; `close()` disposes
- **Models** (4 ORM tables): `OrderRecord`, `FillRecord`, `PositionRecord`, `PnlSnapshotRecord`
