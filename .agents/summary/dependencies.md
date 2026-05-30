# Dependencies

## External (from pyproject.toml)

| Package | Version | Use |
|---------|---------|-----|
| `python` | ^3.12 | Runtime |
| `ib_insync` | ^0.9.86 | IBKR connection (no type stubs; typed as `Any`) |
| `structlog` | ^24.4.0 | Structured logging |
| `pydantic` | ^2.0 | Configuration models |
| `pydantic-settings` | ^2.0 | Settings loading |
| `sqlalchemy` | ^2.0 | ORM persistence (sync only) |
| `rich` | ^13.0 | CLI output formatting |

### Dev Dependencies

| Package | Version | Use |
|---------|---------|-----|
| `pytest` | ^8.0 | Test framework |
| `pytest-asyncio` | ^0.24 | Async test support (`asyncio_mode=auto`) |
| `ruff` | ^0.6 | Linter + formatter (line-length 100, double quotes) |
| `mypy` | ^1.11 | Static type checking (strict mode) |
| `pre-commit` | ^3.0 | Git hooks |
| `coverage` | ^7.0 | Test coverage (source: `src/edrader`) |
| `pyyaml` | — | YAML config loading |
| `types-PyYAML` | — | Stubs for mypy (optional, needs install) |

## Internal Module Dependencies

```
events/
 ├── event_types.py      → BaseEvent, EventPriority (no internal deps)
 ├── bus.py              → event_types, monitoring.logging
 └── journal.py          → event_types, sqlalchemy (async via to_thread)

broker/
 ├── ibkr_client.py      → app.config.BrokerConfig, events.bus, events.event_types, ib_insync (Any)
 ├── market_data.py      → events.bus, events.event_types, ib_insync (Any)
 ├── order_management.py → events.bus, events.event_types, ib_insync (Any)
 └── __init__.py         → task_error_logger helper

risk/
 └── engine.py           → events.bus, events.event_types, monitoring.logging

execution/
 ├── engine.py           → events.bus, events.event_types, execution.sizing, monitoring.logging
 └── sizing.py           → monitoring.logging

portfolio/
 └── position.py         → events.bus, events.event_types, persistence.models, monitoring.logging

strategies/
 ├── base.py             → events.bus, events.event_types, monitoring.logging
 └── examples/
     ├── sma_crossover.py    → strategies.base, events.event_types
     ├── mean_reversion.py   → strategies.base, events.event_types
     └── vwap_reversion.py   → strategies.base, events.event_types

replay/
 ├── clock.py                → monitoring.logging
 ├── engine.py               → events.bus, events.event_types, replay.clock, monitoring.logging
 ├── historical_feed.py      → events.event_types, monitoring.logging
 ├── simulated_broker.py     → events.bus, events.event_types, monitoring.logging
 ├── metrics.py              → events.bus, events.event_types, monitoring.logging
 └── __init__.py             → re-exports all above

monitoring/
 ├── logging.py              → structlog, logging
 ├── metrics.py              → events.bus, events.event_types, monitoring.logging
 └── alerts.py               → events.bus, events.event_types, monitoring.logging

persistence/
 ├── database.py             → persistence.models, sqlalchemy
 └── models.py               → sqlalchemy.orm (DeclarativeBase)

app/
 ├── config.py               → pydantic, yaml
 ├── bootstrap.py            → everything (wires all components), ib_insync.IB
 └── main.py                 → bootstrap.Application

scripts/
 ├── backtest.py             → events.bus, events.journal, events.event_types, execution.engine,
 │                              monitoring.logging, portfolio.position, replay.*, risk.engine,
 │                              strategies.base, strategies.examples.*
 └── loadtest.py             → events.bus, execution.engine, portfolio.position, replay.*,
                                risk.engine, strategies.examples.sma_crossover
```

## Dependency Rules

1. **No circular imports** — module layering: events → strategies/replay → risk/execution/portfolio → monitoring/persistence → app
2. **IBKR types stay in broker/** — `ib_insync.IB` typed as `Any` and only imported in `broker/` and `bootstrap.py`
3. **Strategies only import events** — no dependency on risk, execution, broker, or portfolio
4. **Replay mirrors live dependency structure** — same events, same pipeline; swaps broker and clock implementations
5. **No async DB** — persistence uses sync SQLAlchemy; EventJournal uses `asyncio.to_thread` for SQLite writes
6. **Logging is leaf dependency** — all modules depend on `monitoring.logging` but logging depends on nothing internal
