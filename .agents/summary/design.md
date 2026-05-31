# IBKR Local Trading Platform
## Detailed System Design and Implementation Plan

---

# Document 1 — Detailed System Design

## 1. Goals and Design Philosophy

### Primary Goals

Build a local-first automated trading platform with:

- Interactive Brokers (IBKR) integration
- Custom strategy execution
- Event-driven architecture
- Replayability and observability
- Reliable order management
- Strong modular separation
- Single-machine deployment
- Low operational complexity

### Non-Goals (Initially)

The following are intentionally excluded from the first iterations:

- High-frequency trading (HFT)
- Distributed infrastructure
- Multi-machine clustering
- Multi-user support
- Ultra-low latency optimization
- Complex options portfolio modeling
- GPU acceleration
- Reinforcement learning
- Cloud-native deployment

---

## 2. High-Level Architecture

```text
+-----------------------------------------------------------+
|                   Trading Application                     |
|                                                           |
|  +-------------------+     +--------------------------+   |
|  | Market Data Layer | --> | Strategy Engine          |   |
|  +-------------------+     +--------------------------+   |
|                |                        |                 |
|                v                        v                 |
|       +------------------------------------------+        |
|       |      Internal Event Bus (asyncio)        |        |
|       +------------------------------------------+        |
|                |                        |                 |
|                v                        v                 |
|      +----------------+     +----------------------+     |
|      | Risk Engine    | --> | Execution Engine     |     |
|      +----------------+     +----------------------+     |
|                                               |           |
|                                               v           |
|                                    +------------------+   |
|                                    | Broker Adapter   |   |
|                                    | (IBKR Gateway)   |   |
|                                    +------------------+   |
|                                                           |
|  +----------------+    +-----------------------------+   |
|  | Portfolio      |    | Persistence Layer           |   |
|  +----------------+    +-----------------------------+   |
|                                                           |
|  +-----------------------------------------------------+  |
|  | Logging / Metrics / Replay / Monitoring             |  |
|  +-----------------------------------------------------+  |
+-----------------------------------------------------------+
```

---

## 3. Architectural Style

### Modular Monolith

The entire application runs:

- in a single process
- on a single machine
- inside a single Python runtime

Modules are logically separated but deployed together.

### Event-Driven Runtime

Modules communicate via:

- events
- queues
- asynchronous dispatch

Modules SHOULD NOT:

- directly manipulate each other's internal state
- directly invoke broker operations
- tightly couple to implementation details

---

## 4. Core Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Async Runtime | asyncio |
| Broker Connectivity | IBKR API |
| IBKR Wrapper | ib_async |
| Local Database | SQLite |
| ORM / DB Layer | SQLAlchemy |
| Data Processing | pandas / polars |
| Logging | structlog |
| Serialization | pydantic |
| Testing | pytest |
| Configuration | YAML + pydantic |
| Packaging | Poetry |
| Deployment | Docker (optional) |
| UI (later) | FastAPI + React |

---

## 5. Runtime Model

### Single Async Event Loop

The system operates using:

- one asyncio event loop
- multiple async tasks
- multiple async queues

### Runtime Tasks

```text
main event loop
 ├── broker connection task
 ├── market data ingestion task
 ├── event dispatcher
 ├── strategy execution task
 ├── risk engine task
 ├── execution engine task
 ├── persistence writer
 ├── portfolio tracker
 ├── logging/metrics task
 └── replay recorder
```

---

## 6. Event-Driven Architecture

### Design Principles

Events are:

- immutable
- typed
- timestamped
- serializable

All critical state transitions occur through events.

---

## 7. Event Bus Design

### Core Event Bus

Use:

- asyncio.Queue
- async consumers
- internal dispatcher

### Event Flow

```text
Publisher
   ↓
Event Queue
   ↓
Dispatcher
   ↓
Subscribers
```

### Event Bus Responsibilities

- decouple modules
- preserve ordering
- provide backpressure
- simplify replay
- simplify observability

---

## 8. Event Types

### Market Events

```python
MarketTickEvent
BarCloseEvent
MarketOpenEvent
MarketCloseEvent
```

### Strategy Events

```python
SignalGeneratedEvent
SignalRejectedEvent
StrategyErrorEvent
```

### Execution Events

```python
OrderRequestedEvent
OrderSubmittedEvent
OrderCancelledEvent
OrderFilledEvent
```

### Risk Events

```python
RiskViolationEvent
TradingHaltedEvent
ExposureLimitEvent
```

### Portfolio Events

```python
PositionOpenedEvent
PositionClosedEvent
PnLUpdatedEvent
```

### System Events

```python
HeartbeatEvent
BrokerDisconnectedEvent
BrokerReconnectedEvent
```

---

## 9. Market Data Layer

### Responsibilities

- connect to IBKR market data
- normalize market data
- publish market events
- maintain subscription state
- handle reconnects

### Design Requirements

- support live tick streams
- support aggregated bars
- support historical retrieval
- maintain deterministic timestamps

### Internal Components

```text
market_data/
 ├── feed_manager.py
 ├── tick_normalizer.py
 ├── subscriptions.py
 ├── historical_data.py
 └── aggregators.py
```

---

## 10. Strategy Engine

### Responsibilities

- consume market events
- maintain strategy state
- generate trading signals
- remain broker-independent

### Critical Rule

Strategies MUST NOT:

- directly place orders
- directly access IBKR objects
- directly manage positions

Strategies ONLY emit signals.

---

## 11. Strategy Interface

```python
class Strategy:
    async def on_event(self, event):
        pass

    async def generate_signal(self):
        pass
```

### Strategy Characteristics

Each strategy:

- has isolated state
- subscribes to selected event types
- emits signals asynchronously
- can be independently replayed

---

## 12. Signal Model

```python
Signal(
    strategy_id,
    symbol,
    side,
    confidence,
    suggested_size,
    timestamp
)
```

Signals are advisory.

Execution decides:

- final size
- order type
- routing
- timing
- throttling

---

## 13. Risk Engine

### Responsibilities

- validate signals
- enforce account-level constraints
- monitor exposure
- implement kill switches

### Initial Risk Controls

- max daily loss
- max position size
- max symbol exposure
- max leverage
- max concurrent positions
- stale market protection
- broker disconnect protection

### Output

```text
ApprovedSignal
or
RejectedSignal
```

---

## 14. Execution Engine

### Responsibilities

- convert approved signals into orders
- select order types
- manage retries
- track order lifecycle

### Execution Flow

```text
Signal
  ↓
Sizing
  ↓
Risk Validation
  ↓
Order Request
  ↓
Broker Adapter
```

### Order Types

Initial support:

- Market
- Limit
- Stop

---

## 15. Broker Adapter Layer

### Purpose

Encapsulate all IBKR-specific logic.

### Critical Rule

IBKR types MUST NOT leak outside this module.

Bad:

```python
IBApi.Order
```

Good:

```python
OrderRequest
```

---

## 16. IBKR Integration Design

### Recommended Setup

Use:

- IB Gateway
- paper account initially

Avoid:

- TWS dependency for production runtime

### Connection Requirements

- automatic reconnect
- heartbeat monitoring
- duplicate order protection
- client ID management

---

## 17. Portfolio Engine

### Responsibilities

- maintain positions
- compute realized/unrealized PnL
- compute exposure
- reconcile broker state

### Internal State

```text
positions
cash
realized pnl
unrealized pnl
fees
exposure
```

---

## 18. Persistence Layer

### Initial Database

SQLite

### Why SQLite

- local
- zero maintenance
- ACID compliant
- sufficient for single-user setup

### Stored Data

- market events
- signals
- orders
- fills
- positions
- PnL snapshots
- system logs
- replay journals

---

## 19. Replay System

### Purpose

Replay historical event streams through strategies.

### Benefits

- debugging
- reproducibility
- strategy validation
- regression testing

### Replay Flow

```text
Recorded Events
      ↓
Replay Queue
      ↓
Strategy Engine
```

### Replay Design Principles

The replay engine SHOULD:

- use the same event model as live trading
- use the same strategy code as production
- preserve event ordering
- preserve timestamps
- support accelerated playback
- support deterministic re-execution

### Replay Modes

#### Historical Replay

Feed recorded live events back into the runtime.

Use cases:

- debugging production incidents
- validating strategy behavior
- reproducing fills and signals

#### Synthetic Replay

Generate events from historical OHLCV datasets.

Use cases:

- backtesting
- parameter optimization
- offline research

---

## 20. Backtesting Architecture

### Design Philosophy

The backtesting engine MUST share the same core runtime abstractions as live trading.

Avoid:

- writing separate "backtest-only" strategy code
- duplicating execution logic
- special-case simulation branches inside strategies

The goal is:

```text
same strategy code
same signal generation
same event flow

only data source changes
```

---

### Unified Runtime Model

The system should support two runtime modes:

```text
Live Runtime
    ↓
IBKR Market Data
    ↓
Live Execution
```

and

```text
Backtest Runtime
    ↓
Historical Event Stream
    ↓
Simulated Execution
```

The strategy layer should not know which mode it is running in.

---

### Core Backtesting Components

```text
backtest/
 ├── engine.py
 ├── historical_feed.py
 ├── replay_clock.py
 ├── simulated_broker.py
 ├── fill_model.py
 ├── slippage.py
 ├── commissions.py
 ├── metrics.py
 ├── reporting.py
 └── optimization.py
```

---

### Historical Data Layer

#### Responsibilities

- load historical data
- normalize timestamps
- generate historical events
- feed runtime queues

### Supported Data Types

Initially:

- OHLCV bars
- minute bars
- daily bars

Later:

- tick data
- options chains
- order book data

---

### Historical Event Generation

Historical data should be transformed into the same events used in live trading.

Example:

```python
BarCloseEvent(
    symbol="AAPL",
    open=201.2,
    high=202.1,
    low=200.8,
    close=201.9,
    volume=120000,
    timestamp=...
)
```

This creates:

- strategy parity
- replayability
- deterministic behavior

---

### Replay Clock

The backtesting runtime should include a simulated clock.

### Responsibilities

- control simulated time
- preserve event ordering
- support accelerated execution
- support step-by-step replay

### Replay Modes

#### Fast Mode

Run as quickly as possible.

#### Simulated Real-Time Mode

Respect original timestamps.

#### Step Mode

Advance event-by-event for debugging.

---

### Simulated Broker

The backtesting engine should include a broker simulator.

### Responsibilities

- accept orders
- simulate fills
- compute commissions
- compute slippage
- update positions

The strategy layer should interact with:

```text
Broker Interface
```

not:

```text
IBKR directly
```

This abstraction is critical.

---

### Fill Simulation

The fill model is one of the most important parts of backtesting realism.

### Initial Fill Model

Simple assumptions:

- market orders fill at next bar open
- limit orders fill if touched
- commissions fixed per trade

### Later Enhancements

- partial fills
- queue position modeling
- volume-aware fills
- latency simulation
- spread modeling
- market impact estimation

---

### Slippage Model

Backtests without slippage are misleading.

Initial slippage model:

```text
fixed basis points per trade
```

Later:

- volatility-based slippage
- liquidity-aware slippage
- spread-aware slippage

---

### Commission Model

Include:

- commissions
- exchange fees
- SEC/FINRA fees where applicable

This dramatically affects strategy realism.

---

### Portfolio Simulation

Backtesting should use the same portfolio engine used in live trading.

### Portfolio State

- positions
- realized pnl
- unrealized pnl
- cash
- leverage
- exposure

---

### Metrics Engine

Initial metrics:

- cumulative return
- Sharpe ratio
- Sortino ratio
- max drawdown
- win rate
- average holding time
- exposure utilization
- turnover

---

### Backtest Reports

Generate:

- equity curve
- drawdown chart
- trade log
- position history
- risk metrics
- monthly return breakdown

---

### Parameter Optimization

Later enhancement.

### Recommended Approach

Use:

- parameter sweeps
- grid search
- walk-forward validation

Avoid initially:

- overfitting
- excessive hyperparameter search
- black-box optimization

---

### Walk-Forward Testing

Strongly recommended.

Example:

```text
Train: Jan-Jun
Test: Jul

Train: Feb-Jul
Test: Aug
```

This better approximates live deployment.

---

### Event Journal Integration

Backtests should optionally persist all generated events.

Benefits:

- debugging
- replay
- regression testing
- comparing strategy versions

---

### Deterministic Replay Requirement

A critical architectural principle:

```text
same inputs
same config
same event stream

must produce same outputs
```

This dramatically improves:

- debugging
- confidence
- reproducibility

---

### Recommended Development Order for Backtesting

#### Stage 1

Bar-based historical replay.

#### Stage 2

Basic simulated fills.

#### Stage 3

Portfolio accounting.

#### Stage 4

Metrics and reporting.

#### Stage 5

Tick-level replay.

#### Stage 6

Optimization and walk-forward testing.

---

## 20. Logging and Observability

### Logging Requirements

All critical events MUST be logged.

### Log Categories

- market data
- signals
- orders
- fills
- risk decisions
- reconnect events
- exceptions

### Recommended Logging Style

Structured JSON logs.

---

## 21. Configuration System

### Configuration Sources

- YAML files
- environment variables

### Config Categories

```text
broker settings
strategy settings
risk settings
symbols
logging
replay
```

---

## 22. Error Handling Philosophy

### Principles

- fail isolated modules
- avoid crashing entire runtime
- preserve replayability
- emit explicit failure events

### Error Categories

- transient broker errors
- invalid market data
- rejected orders
- strategy exceptions
- database failures

---

## 23. Concurrency Model

### Recommended Approach

Use:

- asyncio coroutines
- queues
- cooperative concurrency

Avoid initially:

- threads
- multiprocessing
- distributed queues

### Why

Benefits:

- deterministic ordering
- simpler debugging
- fewer race conditions
- easier replay

---

## 24. Internal Project Structure

```text
edrader/
│
├── app/
│   ├── main.py
│   ├── bootstrap.py
│   └── config.py
│
├── broker/
│   ├── ibkr_client.py
│   ├── market_data.py
│   ├── orders.py
│   └── adapters.py
│
├── events/
│   ├── bus.py
│   ├── dispatcher.py
│   ├── event_types.py
│   └── subscribers.py
│
├── strategies/
│   ├── base.py
│   ├── momentum.py
│   └── mean_reversion.py
│
├── execution/
│   ├── executor.py
│   ├── sizing.py
│   └── order_manager.py
│
├── risk/
│   ├── rules.py
│   ├── limits.py
│   └── kill_switch.py
│
├── portfolio/
│   ├── positions.py
│   ├── pnl.py
│   └── reconciliation.py
│
├── persistence/
│   ├── db.py
│   ├── models.py
│   └── repositories.py
│
├── replay/
│   ├── recorder.py
│   └── player.py
│
├── monitoring/
│   ├── logging.py
│   ├── metrics.py
│   └── alerts.py
│
├── tests/
│
└── configs/
```

---

## 25. Deployment Model

### Initial Deployment

Single local machine.

### Recommended Runtime

- Linux or macOS
- Python virtual environment
- IB Gateway running locally

### Optional Packaging

Docker container.

---

## 26. Future Extensions

### Potential Enhancements

- multi-strategy portfolio allocator
- options support
- strategy optimization engine
- web dashboard
- Prometheus metrics
- ML inference engine
- distributed backtesting
- PostgreSQL migration
- cloud deployment

---

