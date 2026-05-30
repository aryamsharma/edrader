# Trading System Documentation

## Summary

`edrader` is an event-driven algorithmic trading system supporting both live (IBKR) and backtested execution through a shared event pipeline. 26 domain event types flow from strategies through RiskEngine → ExecutionEngine → Broker → PositionManager. Backtest mode uses sync dispatch for 8.4× speedup (22s for 140k bars × 2 strategies).

## Quick Links

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System design, principles, component substitution, key decisions |
| [Components](components.md) | All 20+ components with class details and file paths |
| [Interfaces](interfaces.md) | Complete API signatures for all public classes |
| [Data Models](data_models.md) | 26 event types, SQLite journal schema, 4 ORM models, config |
| [Workflows](workflows.md) | Live trading, backtest, kill switch, journal, throttle, fill flows |
| [Dependencies](dependencies.md) | External packages, internal module graph, import rules |

## Directory Structure

```
src/edrader/
├── app/           # bootstrap.py (Application lifecycle), config.py (pydantic), main.py
├── broker/        # ibkr_client.py, market_data.py, order_management.py, __init__.py
├── events/        # event_types.py (26 types), bus.py (EventBus), journal.py (SQLite)
├── execution/     # engine.py (ExecutionEngine), sizing.py (SizingEngine)
├── monitoring/    # logging.py (structlog), metrics.py (MetricsCollector), alerts.py (AlertManager)
├── persistence/   # database.py (DatabaseManager), models.py (4 ORM tables)
├── portfolio/     # position.py (PositionManager, Position, ExposureSnapshot)
├── replay/        # clock.py, engine.py, historical_feed.py, simulated_broker.py, metrics.py
├── risk/          # engine.py (RiskEngine: 6 checks + kill switch)
└── strategies/    # base.py (Strategy, StrategyLoader), examples/ (3 strategies)

scripts/
├── backtest.py    # End-to-end backtest runner
└── loadtest.py    # Subscriber-scaling latency profiler
```

## Key Metrics

| Metric | Value |
|--------|-------|
| Event types | 26 frozen dataclass types |
| Event priority levels | 4 (LOW, NORMAL, HIGH, CRITICAL) |
| Tests | 434 (22 files, pytest-asyncio) |
| Backtest events | 140k 1-min bars |
| Backtest strategies | 2 (SmaCrossover + MeanReversion) |
| Baseline runtime | 184s |
| Optimized runtime | 22s (8.4× faster) |
| Journal overhead (140k events) | ~3.7s with fast_mode |
| Linting | ruff: 0 errors expected |
| Type checking | mypy strict: 1 known error (yaml stubs) |
| Formatting | ruff, line-length 100, double quotes |
| Python | ^3.12 |

## Development Commands

```sh
poetry run pytest                              # All 434 tests
poetry run ruff check .                         # Lint (0 errors expected)
poetry run ruff check --fix .                   # Lint + fix
poetry run ruff format .                        # Format
poetry run mypy src/                            # Typecheck (1 known yaml-stubs error)
poetry run pre-commit run --all-files           # All hooks
poetry run python scripts/backtest.py <csv>                   # Bar backtest
poetry run python scripts/backtest.py <csv> --tick             # Tick backtest
poetry run python scripts/backtest.py <csv> --journal --verbose  # With journal + debug
poetry run python scripts/loadtest.py <csv>                    # Loadtest profiler
poetry run python -m edrader.app.main           # Run live (needs IB Gateway)
```

## Test Conventions

- Async by default (`asyncio_mode = auto`)
- Import directly from `edrader.*` via `pythonpath = ["src"]`
- After `EventBus.publish()`, call `await event_bus.drain()` before assertions
- `tmp_path` for SQLite tests, `MagicMock`/`AsyncMock` for IBKR tests
- Mock `ib` injected via constructor; never requires live TWS/Gateway
- `collected_events` fixture with `subscribe_all` + `drain()`
