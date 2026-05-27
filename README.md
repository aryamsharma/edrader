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
