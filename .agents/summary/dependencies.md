# External Dependencies

## Runtime Dependencies

| Package | Version | Used In | Purpose |
|---|---|---|---|
| pydantic | ^2.0 | `app/config.py` | `BaseModel` configuration hierarchy with validation and `Field(default_factory=...)` |
| pydantic-settings | ^2.0 | (declared but unused) | Environment variable override support for config |
| structlog | ^24.0 | `monitoring/logging.py`, all modules | Structured logging with context vars, ISO timestamps, JSON output |
| pyyaml | ^6.0 | `app/config.py` | YAML config file parsing via `yaml.safe_load()` |
| sqlalchemy | ^2.0 | `events/journal.py` | `create_engine`, `Session`, `DeclarativeBase` for append-only event journal |
| ib-insync | ^0.9.86 | `broker/ibkr_client.py`, `broker/market_data.py` | IBKR API wrapper — `IB()`, `Stock()`, `Contract()` |

## Dev Dependencies

| Package | Version | Purpose |
|---|---|---|
| pytest | ^8.0 | Test framework with fixtures, parameterization |
| pytest-asyncio | ^0.24 | Async test support (`asyncio_mode = auto`) |
| pytest-cov | ^5.0 | Coverage reporting |
| ruff | ^0.7 | Linting (`ruff check`) and formatting (`ruff format`) |
| mypy | ^1.12 | Static type checking (strict mode with `disallow_untyped_defs`) |
| pre-commit | ^4.0 | Git hook framework running ruff, mypy, trailing-whitespace, YAML/JSON checks |

## Dependency Gotchas

- **ib_insync has no type stubs** — must use `# type: ignore[no-untyped-call]` on `IB()` constructor and typed as `Any` in broker module
- **SQLAlchemy column access** needs `# type: ignore[assignment]` / `# type: ignore[arg-type]` for mypy compatibility
- **reconnect_interval** in `BrokerConfig` is `float` (not int) — important for test speed
- **poetry.lock** is gitignored — excluded from version control intentionally
- **pydantic-settings** is declared but not yet used in any source file

## Third-Party Type Stubs

No third-party type stubs are installed. `ignore_missing_imports = true` in mypy config suppresses errors for `ib_insync` and `structlog`.
