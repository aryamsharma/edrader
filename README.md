# Trading Platform

Event-driven modular trading platform for Interactive Brokers. Built with Python 3.12+, asyncio, and 27 domain event types.

## Prerequisites

- **Python 3.12+**
- **Poetry** (package manager) — install via `pip install poetry` or `brew install poetry`
- **IB Gateway** or **TWS** (for live/paper trading) — [download](https://www.interactivebrokers.com/en/trading/ib-gateway.php)
  - Enable API connections in Configuration → API → Enable ActiveX and Socket Clients
  - Default port: `4001` (paper) / `7496` (live)

## Setup

```sh
git clone <repo>
cd trading-platform

# Install all dependencies (including dev)
poetry install

# Activate the virtual environment
poetry shell

# Install pre-commit hooks
pre-commit install
```

## Dependencies

| Dependency | Purpose |
|---|---|
| `pydantic` / `pydantic-settings` | Configuration validation |
| `structlog` | Structured logging (JSON + console) |
| `pyyaml` | YAML config file loading |
| `sqlalchemy` | ORM for persistence (sync, SQLite) |
| `ib-insync` | Interactive Brokers API client |

### Dev Dependencies

| Tool | Purpose |
|---|---|
| `pytest` / `pytest-asyncio` | Test runner (async by default) |
| `pytest-cov` | Coverage reporting |
| `ruff` | Linter + formatter |
| `mypy` | Static type checking (strict mode) |
| `pre-commit` | Git hooks (ruff, mypy, trailing whitespace, etc.) |
| `alembic` | Database migrations |

## Configuration

Default config uses paper trading defaults. Override via YAML:

```sh
# Create a local config override
cp configs/default.yaml configs/local.yaml
# Edit configs/local.yaml as needed
```

Key config paths:

| Variable | Default | Description |
|---|---|---|
| `broker.port` | 4001 | IBKR port (4001 paper, 7496 live) |
| `broker.client_id` | 1 | Unique client ID per connection |
| `persistence.database_url` | `sqlite:///data/trading.db` | Database path |
| `app.environment` | `development` | One of: `development`, `paper`, `live` |

## Running

### Live / Paper Trading

Requires IB Gateway or TWS running with API enabled:

```sh
poetry run python -m edrader.app.main
```

### Tests

```sh
# Run all tests (excludes 1 known flaky)
poetry run pytest -k "not test_stop_during_run"

# Run a specific test file
poetry run pytest tests/test_event_bus.py -v
```

### Lint & Typecheck

```sh
poetry run ruff check .        # Lint
poetry run ruff format .       # Format
poetry run mypy src/           # Typecheck (strict)
```

Order: `ruff check → ruff format → mypy → pytest`

## Project Structure

```
src/edrader/
├── app/           # Bootstrap, config, main
├── broker/        # IBKR client, market data, order management
├── events/        # Domain events (27 types), event bus, journal
├── execution/     # Signal→order pipeline, sizing
├── monitoring/    # Logging, metrics collector, alert manager
├── persistence/   # SQLAlchemy engine, 4 ORM models
├── portfolio/     # Position tracking, PnL, exposure
├── replay/        # Backtesting: clock, historical feed, simulated broker, metrics
├── risk/          # 6 risk checks, kill switch
└── strategies/    # Base class, loader, example strategies (SMA crossover, mean reversion)
```

## Architecture

Event-driven: strategies emit signals → risk engine validates → execution engine places orders → broker adapter sends to IBKR → position manager tracks fills. See `.agents/summary/` for full documentation (architecture, components, interfaces, workflows).

## Web UI

### Recommended Approach: In-Process FastAPI + WebSocket Bridge

Embed a lightweight HTTP/WS server in the same process as the trading engine. The existing `EventBus.subscribe_all()` method already delivers every event in real-time — a WebSocket bridge is the only new code needed.

```
Browser (React / Svelte / vanilla JS)
    ↕ WebSocket (JSON events)
FastAPI server (added to Application.startup())
    ├── WS /events      → subscribe_all → push JSON to browser
    ├── GET /positions   → PositionManager.positions
    ├── GET /exposure    → PositionManager.exposure()
    ├── GET /metrics     → MetricsCollector runtime snapshots
    ├── POST /order      → publish OrderRequestedEvent
    └── POST /strategy   → load / start / stop strategies
EventBus ←→ All Components (existing)
```

### Why This Works

| Feature | How It's Already Ready |
|---|---|
| **Real-time event stream** | `EventBus.subscribe_all()` + 27 event types with `to_dict()` == instant WebSocket feed |
| **State queries** | `PositionManager`, `MetricsCollector`, `RiskEngine` are all queryable Python objects in the same process |
| **Order placement** | Publishing `OrderRequestedEvent` from a REST handler takes one line |
| **Strategy lifecycle** | `StrategyLoader.create()` + `strategy.start()` / `strategy.stop()` are already async |
| **Zero new instrumentation** | The journal already logs everything; the bus already dispatches everything |

### Alternatives Considered

| Approach | When to Consider |
|---|---|
| **Sidecar process** (separate FastAPI + Redis pub/sub) | If trading loop CPU usage is consistently >80% and UI responsiveness matters more than simplicity |
| **Grafana + Prometheus** | Read-only monitoring dashboards — MetricsCollector already emits structured data. Add `prometheus-client` export and point Grafana at it. |
| **Electron / Tauri desktop** | If you need local IB Gateway bundling or offline capability. Significantly more build complexity. |
| **CLI / TUI only** | For headless/server deployments. The app already runs fully without a UI. |

### Dependency Changes

Add to `pyproject.toml`:

```
fastapi = "^0.115"
uvicorn = {version = "^0.32", extras = ["standard"]}
websockets = "^14"
```

### Minimal Implementation Sketch

A new `src/edrader/web/server.py` with an async lifespan that registers routes, and a few lines in `Application.startup()`:

```python
async def startup(self) -> None:
    ...
    self._web = WebServer(self.event_bus, self)
    await self._web.start()  # launches uvicorn in a task
```

The WebSocket bridge handler:

```python
@router.websocket("/events")
async def event_stream(ws: WebSocket) -> None:
    await ws.accept()
    async def push(event: BaseEvent) -> None:
        await ws.send_json(event.to_dict())
    unsub = event_bus.subscribe_all(push)
    try:
        while True:
            await ws.receive_text()  # keepalive
    except WebSocketDisconnect:
        unsub()
```

## Architecture Rationale

### Why Event-Driven Modular Monolith?

The system is built as a **single-process event-driven monolith** — one asyncio event loop with typed domain events as the only cross-module communication. This was chosen for the following reasons:

| Concern | Why This Architecture Fits |
|---|---|
| **Latency** | Single process, no serialization overhead between components. Events flow through the bus at microsecond latency. |
| **Data consistency** | Position, risk, and execution state live in the same process — no distributed transactions, no eventual consistency headaches. |
| **Live/backtest parity** | Same code path for both modes — only the data source and broker differ. Events are the abstraction boundary. |
| **Observability** | Every event passes through the journal — full audit trail with zero instrumentation. |
| **Iteration speed** | 20 test files, 435 tests, instant feedback loop. No service deployment overhead. |

### Scaling Dimensions

When the application needs to grow, the event-driven foundation maps naturally to a distributed architecture. Each bounded context becomes an independent service connected by a streaming event backbone (Kafka / Redpanda / NATS).

```
Current: EventBus (in-process queues)
         ↓
Future:  Kafka Topic (partitioned event stream)
```

| Scale Dimension | Trigger | Target Architecture |
|---|---|---|
| **More strategies (100s)** | Single process CPU-bound on signal computation | Strategy workers as stateless consumers, scaled by symbol shard or strategy type |
| **Higher market data volume** | Tick rate exceeds single-thread throughput | Dedicated market data ingestion service, fan-out to strategy workers |
| **Multiple brokers / liquidity providers** | Need to route orders to IBKR, Coinbase, FXCM simultaneously | Broker gateway per provider — each subscribes to `OrderRequestedEvent`, translates to provider-specific API |
| **Multi-user / multi-portfolio** | Separate risk limits, PnL tracking per account | Position/Risk as a single-writer service, queried by strategy workers |
| **Geographic distribution** | Latency-sensitive strategies need colo | Strategy workers deployed per region, upstream sequencer for global event ordering |
| **Global sequence ordering** | Deterministic replay and audit across services | Formal **Sequencer** service — assigns monotonic sequence at event ingest before any consumer sees it |

### Service Decomposition Map

Each box represents a potential microservice, matching the current module boundaries:

```
Market Data Feed ──→ Kafka ──→ Strategy Workers ──→ Risk Service ──→ Execution Service
      │                      ↗                           │                    │
      │                     │                            ▼                    ▼
      │                     │                     Event Stream          Broker Gateway
      │                     │                                               │
      ▼                     │                                               ▼
Position Service ←──────── Event Stream ←──────────────────────────── Order Filled
      │
      ▼
Metrics / Alerts (observers)
```

### Sequencing

The current system uses a single dispatch task with dual priority queues. Events are sequenced at journal-write time during dispatch.

For distributed/HFT-grade requirements, a **Sequencer** service is inserted at the event ingest boundary — assigns a global, monotonically increasing sequence number before any consumer processes the event. This enables:

- Deterministic replay across services
- Exactly-once processing semantics
- Chronological ordering even across priority levels
- Time-based partitioning for backtesting reconciliation

The event serialization (`to_dict()` / `from_dict()`) and typed event contracts are already in place — adding a sequencer changes no existing code, only inserts a new service between `publish()` and the streaming backbone.
