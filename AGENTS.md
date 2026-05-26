# AGENTS.md

## Commands

```sh
poetry run pytest                      # All 127 tests, verbose
poetry run pytest -k "test_priority"   # Keyword filter
poetry run pytest --cov                # With coverage
poetry run ruff check .                # Lint (0 errors expected)
poetry run ruff check --fix .          # Lint + fix
poetry run ruff format .               # Format (line-length 100, double quotes)
poetry run mypy src/                   # Strict typecheck (0 errors expected)
poetry run pre-commit run --all-files  # All hooks
poetry run python -m trading_platform.app.main  # Run app (needs IB Gateway)
```

Order: `ruff check -> ruff format -> mypy -> pytest`.

## Architecture

- **Modular monolith**, single process, single asyncio event loop
- 11 module dirs under `src/trading_platform/`; 6 are stubs: `execution/`, `persistence/`, `portfolio/`, `replay/`, `risk/`, `strategies/`
- Events (`BaseEvent`) are the single source of truth — frozen dataclasses with `slots=True`, UUID `event_id`, UTC `timestamp`, `EventPriority` (LOW/NORMAL/HIGH/CRITICAL), `to_dict()`/`from_dict()` serialization. 25 concrete event types in `events/event_types.py`.
- `EventBus` uses dual `asyncio.Queue` (high-priority vs. normal), typed `subscribe()`, wildcard `subscribe_all()`, optional predicate filters, error handler callbacks
- `EventJournal` is SQLite append-only store for replay/audit
- **IBKR types MUST NOT leak outside `broker/`** — the ib_insync `IB` object is private. All inter-module communication uses domain events.
- **Strategies emit signals only** — they never place orders, call IBKR, or manage positions.
- Same code path runs live and in backtest; only the data source/clock changes.
- **`MarketDataFeed`** (`broker/market_data.py`) manages tick subscriptions via `ib_insync`, publishes `MarketTickEvent`, aggregates `BarCloseEvent` per symbol, auto re-subscribes on `BrokerReconnectedEvent`
- **`DatabaseManager`** (`persistence/database.py`) provides centralized SQLAlchemy engine, session lifecycle, and `init_db()`/`close()` for domain tables
- **Persistence Models** (`persistence/models.py`): `OrderRecord`, `FillRecord`, `PositionRecord`, `PnlSnapshotRecord`; Alembic migrations in `migrations/`

## Implementation Status

| Phase | Status |
|---|---|
| P0 — Foundation (config, logging, tooling) | ✅ |
| P1 — Event Infrastructure (types, bus, journal) | ✅ |
| P2.1 — Connection Manager (`IBKRClient`) | ✅ |
| P2.2 — Market Data Feed (`MarketDataFeed`) | ✅ |
| P2.3 — Order Connectivity (`BrokerAdapter`) | ✅ |
| P3.1 — Persistence Infrastructure (`DatabaseManager`, models, Alembic) | ✅ |
| P3.2–P10 — Portfolio, Strategies, Risk, Execution, Replay, Monitoring | ⏳ |

177 tests passing across 11 test files. Detailed docs at `docs/design.md`, `docs/implementation_plan.md`, `docs/status.md`.

## Test Conventions

- `pytest-asyncio` with `asyncio_mode = auto` — tests are async by default
- `pythonpath = ["src"]` in pyproject.toml — import directly from `trading_platform.*`
- After `EventBus.publish()`, call `await event_bus.drain()` before asserting collected events
- Use `tmp_path` for SQLite journal tests, `MagicMock`/`AsyncMock` for IBKR client tests
- IBKR client/market data tests: inject mock `ib` via constructor; never require a live TWS/Gateway
- Class-based grouping (e.g., `TestIBKRClientConnect`, `TestMarketDataFeedSubscribe`)
- `collected_events` fixture with `subscribe_all` + `drain()` for event assertions

## Key Conventions

- ruff: line-length 100, double quotes, lint rules `E,F,I,N,W,UP,B,SIM,ARG`
- mypy: strict mode, `disallow_untyped_defs = true`, excludes `tests/`
- All dataclasses: `@dataclass(frozen=True, slots=True)` except where mutation is needed
- All events: inherit `BaseEvent`, add domain-specific fields, `priority` for HIGH/CRITICAL routing
- All async handlers: typed as `Callable[[BaseEvent], Awaitable[None]]`
- All public methods: fully typed (return types, argument types)
- Config: pydantic `BaseModel` with `Field(default_factory=...)` for nested defaults, YAML loading via `load_config()`
- Logging: `structlog` via `get_logger(__name__)`, context vars for structured fields
- Commit style: `Phase X.Y: description` or `docs: description`

## Gotchas

- `ib_insync.IB` has no type stubs — typed as `Any` in broker module, `type: ignore[no-untyped-call]` on `IB()` constructor
- SQLAlchemy column access needs `# type: ignore[assignment]` / `# type: ignore[arg-type]` for mypy compatibility
- `reconnect_interval` in `BrokerConfig` is `float` (not int) — important for test speed
- `configs/` and `data/` dirs are empty at setup; `data/trading.db` is gitignored via `*.db` and `*.sqlite` patterns
- `poetry.lock` IS in `.gitignore` — intentionally excluded from version control
- `opencode.json` at project root configures MCP server and plugin; restart opencode after changes
- `Contract()` second arg is `sec_type` (str) but mypy sees it as `int` since ib_insync has no stubs — use `# type: ignore[arg-type]`
- Bar aggregation is tick-triggered: a bar is emitted when a new tick arrives AFTER the time window has elapsed

## Custom Instructions

<!-- This section is maintained by developers and agents during day-to-day work.
     It is NOT auto-generated by codebase-summary and MUST be preserved during refreshes.
     Add project-specific conventions, gotchas, and workflow requirements here. -->
