# Dependencies

## Runtime Dependencies

### pydantic ^2.0
- **Purpose:** Configuration management with type validation
- **Usage patterns:**
  - `BaseModel` subclasses for each config section (`AppConfig`, `BrokerConfig`, etc.)
  - `Field(default_factory=...)` for nested default instances
  - YAML loading via `yaml.safe_load()` → `TradingConfig(**raw)`
  - `Literal` types for constrained string fields (e.g., `environment: Literal["development", "paper", "live"]`)
- **Files:** `app/config.py`

### structlog ^24.0
- **Purpose:** Structured, contextual logging
- **Usage patterns:**
  - `get_logger(__name__)` in every module
  - `contextvars` integration for request/task-level context
  - Console renderer for TTY, JSON renderer for non-TTY
  - Filtering bound loggers via `structlog.make_filtering_bound_logger`
  - Log calls use event name + keyword args: `logger.info("event_name", key=value)`
- **Files:** `monitoring/logging.py` (setup), used in every module

### pyyaml ^6.0
- **Purpose:** YAML config file parsing
- **Usage patterns:** `yaml.safe_load()` in `load_config()`
- **Files:** `app/config.py`

### SQLAlchemy ^2.0
- **Purpose:** ORM for persistence
- **Usage patterns:**
  - `DeclarativeBase` for model definitions
  - Column types: `Integer`, `String`, `Float`, `DateTime`
  - `create_engine()` with SQLite (default: `sqlite:///data/trading.db`)
  - Manual session management via `Session()` + commit/rollback
  - No async — runs in sync via `Session` (not `AsyncSession`)
  - `contextmanager` pattern for session lifecycle in `DatabaseManager`
- **Files:** `persistence/database.py`, `persistence/models.py`, `events/journal.py`

### ib_insync ^0.9.86
- **Purpose:** Interactive Brokers API client
- **Usage patterns:**
  - No type stubs — typed as `Any`, `# type: ignore[no-untyped-call]` on constructor
  - `IB()` constructor, `.connectAsync()`, `.disconnect()`
  - `disconnectedEvent.connect()` / `.disconnect()` for event handlers
  - `pendingTickersEvent` for market data callbacks
  - `orderStatusEvent`, `execDetailsEvent` for order tracking
  - `reqMktData()`, `cancelMktData()` for subscriptions
  - `placeOrder()`, `cancelOrder()` for order management
  - `Stock()`, `Contract()`, `MarketOrder()`, `LimitOrder()`, `StopOrder()` helper classes
  - `Contract()` second arg is `sec_type` (str) but mypy sees it as `int` — `# type: ignore[arg-type]`
- **Files:** `broker/ibkr_client.py`, `broker/market_data.py`, `broker/order_management.py`

## Development Dependencies

### pytest ^8.0
- **Purpose:** Test framework
- **Configuration:** `asyncio_mode = auto`, `pythonpath = ["src"]`
- **Test convention:** Async tests by default, class-based grouping
- **Plugins:** `pytest-asyncio`, `pytest-cov`

### ruff ^0.7
- **Purpose:** Linting and formatting
- **Configuration:** Line-length 100, double quotes, rule set `E,F,I,N,W,UP,B,SIM,ARG`
- **Commands:** `ruff check .`, `ruff format .`

### mypy ^1.12
- **Purpose:** Static type checking
- **Configuration:** Strict mode, excludes `tests/`
- **Files:** Strict checks on all `src/` files

### pre-commit ^4.0
- **Purpose:** Git hooks
- **Configuration:** `.pre-commit-config.yaml`

### alembic ^1.13
- **Purpose:** Database migrations
- **Files:** `migrations/`, `alembic.ini`

## Design Constraints

- **No strict type stubs for ib_insync** — `Any` typing required in broker module
- **SQLAlchemy column access** needs `# type: ignore[assignment]` / `# type: ignore[arg-type]` for mypy compatibility
- **No `__init__.py` re-exports** — all imports direct from their modules
- **No external web framework** — no FastAPI/Flask; monitoring via internal metrics only
- **No async DB** — persistence is sync in a threadpool (SQLAlchemy sync sessions)
