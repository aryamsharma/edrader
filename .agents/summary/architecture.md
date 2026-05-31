# Architecture

## High-Level Design

Modular monolith, single process, single asyncio event loop. All inter-component communication flows through the `EventBus` as typed domain events (26 frozen dataclass types). The same code path handles live trading and backtesting — only the data source, clock, and broker implementation differ. Event execution spans a pipeline of risk validation, sizing, order submission, simulated/live fill, position tracking, and metrics collection.

```
Live:   IBKR Gateway → MarketDataFeed → EventBus → RiskEngine → ExecutionEngine → BrokerAdapter → PositionManager
Backtest: HistoricalFeed → EventBus  → RiskEngine → ExecutionEngine → SimulatedBroker → PositionManager
```

## Core Principles

1. **Events as single source of truth** — 26 frozen dataclass event types with `to_dict()`/`from_dict()` serialization. EventJournal persists all events to SQLite for replay and audit.
2. **IBKR types stay in broker/** — `ib_async.IB` typed as `Any` (no stubs), all cross-module communication uses domain events.
3. **Strategies receive events, emit signals** — never place orders, call IBKR, or manage positions. Each strategy declares which event types it subscribes to via `event_types()`.
4. **Lifecycle-managed components** — `start()`/`stop()` with idempotency guards; unsubscribe callables tracked and cleared on stop.
5. **Live and backtest share code path** — only data source (MarketDataFeed vs HistoricalFeed), clock (wall vs replay), and broker (BrokerAdapter vs SimulatedBroker) differ.

## Event Flow (Signal → Fill)

```
Strategy.on_event(event)
  → if signal triggered: emit_signal(symbol, side, confidence, size)
  → EventBus.publish(SignalGeneratedEvent)

RiskEngine subscriber:
  → 6 checks (max_position_size, max_daily_loss, max_leverage, max_symbol_exposure,
              max_concurrent_positions, stale_market)
  → kill_switch blocks all signals
  → publish SignalApprovedEvent or SignalRejectedEvent (+ RiskViolationEvent on reject)

ExecutionEngine subscriber:
  → throttle check (per-symbol cooldown)
  → SizingEngine.compute_size() → final quantity
  → publish OrderRequestedEvent

SimulatedBroker subscriber:
  → create order, fill at current price (or hold for next price tick)
  → publish OrderSubmittedEvent → OrderStatusChangedEvent(Filled) → OrderFilledEvent
  → 3 events per fill

PositionManager subscriber:
  → update position (avg_cost, realized_pnl)
  → publish PositionOpenedEvent / PositionClosedEvent / PnLUpdatedEvent / PositionUpdate
  → publish ExposureUpdatedEvent (gross/net exposure, leverage, equity)

MetricsEngine subscriber:
  → track equity curve, trade outcomes, traded value
  → compute(): total_return, sharpe, max_drawdown, win_rate
```

## Component Substitutability

| Live | Backtest |
|------|----------|
| `MarketDataFeed` (IBKR ticks/bars) | `HistoricalFeed` (CSV file) |
| `BrokerAdapter` (IBKR orders) | `SimulatedBroker` (price-based fill) |
| `IBKRClient` (connection) | — |
| Wall clock | `ReplayClock` (simulated) |
| `EventBus` (async dispatch) | `EventBus` (sync_mode during replay) |

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `sync_mode` for backtest | `EventBus.sync_mode = True` makes `publish()` dispatch subscribers synchronously, eliminating asyncio task-switching overhead (8.4× speedup: 184s → 22s) |
| PriorityQueue get() fast path | `get_nowait()` on both queues first, then 1ms `wait_for(high.get())` fallback, then blocking `normal.get()` — avoids 10ms timeout |
| Sub-1ms sleep skip | `_wait_for_next` skips `asyncio.sleep` when adjusted delta < 1ms (below OS timer resolution) |
| SimulatedBroker 3-events-per-fill | Each fill publishes Submitted + StatusChanged + Filled — contributes significantly to pipeline cost |
| Journal batch writes | `batch_size` buffers events; `flush()` does raw SQL `executemany`; 4.2× faster than per-row inserts |
| SizingEngine decoupled | Separate class with method-based sizing (fixed, percent_equity, volatility) |
| No per-bar drain() in backtest | `sync_mode` eliminates need to `await drain()` between events |

## Dual Metrics System

- **`MetricsCollector`** (monitoring/): live runtime statistics — throughput, event counts, queue depth, subscriber counts; periodic sampling.
- **`MetricsEngine`** (replay/): backtest performance — equity curve, total return, Sharpe ratio, max drawdown, win rate, turnover; `compute()` returns `BacktestMetrics` dataclass.

## Files

- `src/edrader/events/bus.py` — EventBus, PriorityQueue, DispatchMetrics, SubscriberEntry
- `src/edrader/events/event_types.py` — 26 event types, BaseEvent, EventPriority enum
- `src/edrader/events/journal.py` — EventJournal with SQLite persistence
- `src/edrader/app/bootstrap.py` — Application lifecycle, wiring for live/simulated/monitoring
- `src/edrader/app/config.py` — Pydantic settings (TradingConfig, BrokerConfig, etc.)
- `scripts/backtest.py` — End-to-end backtest runner
- `scripts/loadtest.py` — Step-by-step loadtest profiler
