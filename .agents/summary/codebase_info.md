# Codebase Information

## Overview
**Name:** edrader  
**Version:** 0.1.0  
**Description:** Event-driven modular trading platform for Interactive Brokers  
**Language:** Python 3.12+  
**Architecture:** Modular monolith, single process, single asyncio event loop  

## Statistics
- **Source files:** 37 Python files in `src/edrader/` (11 module dirs, 17 modules + 12 `__init__.py` + 8 non-init source files)
- **Test files:** 22 Python files in `tests/` (443 tests, 1 flaky excluded)
- **Config:** YAML-based (pydantic), defaults in `pyproject.toml`
- **Event types:** 27 concrete event types inheriting `BaseEvent`

## Project Structure
```
src/edrader/
├── __init__.py
├── app/           # Application bootstrap, config, main entry
├── broker/        # IBKR integration (client, market data, orders)
├── events/        # Event system (types, bus, journal)
├── execution/     # Signal→order pipeline, sizing
├── monitoring/    # Logging, metrics, alerts
├── persistence/   # Database (SQLAlchemy models, manager)
├── portfolio/     # Position tracking, PnL, exposure
├── replay/        # Backtesting (clock, engine, feed, broker, metrics)
├── risk/          # Risk engine (signal checks, kill switch)
└── strategies/    # Strategy framework + examples (SMA, mean reversion)

tests/
├── conftest.py
├── test_bootstrap.py
├── test_broker.py
├── test_config.py
├── test_event_bus.py
├── test_event_types.py
├── test_execution.py
├── test_ibkr_client.py
├── test_integration.py
├── test_journal.py
├── test_logging.py
├── test_market_data.py
├── test_metrics.py
├── test_monitoring.py
├── test_order_management.py
├── test_persistence.py
├── test_portfolio.py
├── test_replay.py
├── test_risk.py
├── test_simulated_broker.py
├── test_strategies.py
└── test_strategy_examples.py
```

## Key Technologies
| Library | Purpose | Usage |
|---|---|---|
| pydantic ^2.0 | Configuration | `TradingConfig`, sub-configs, YAML loading |
| structlog ^24.0 | Structured logging | All modules via `get_logger(__name__)` |
| SQLAlchemy ^2.0 | ORM | Domain models (OrderRecord, FillRecord, etc.) |
| ib_insync ^0.9.86 | IBKR API | `IBKRClient`, `MarketDataFeed`, `BrokerAdapter` |
| pytest ^8.0 | Testing | 443 tests, asyncio_mode=auto |
| ruff ^0.7 | Linting/formatting | 100 char line-length, double quotes |
| mypy ^1.12 | Type checking | Strict mode, excludes tests/ |
| alembic ^1.13 | Migrations | Database schema migrations |

## Design Principles
- **Events as single source of truth**: All inter-module communication via domain events on `EventBus`
- **IBKR isolation**: `ib_insync` types never leak outside `broker/` module
- **Strategies emit signals only**: Never place orders or manage positions directly
- **Same code for live and backtest**: Only data source and clock differ
- **All components are lifecycle-managed**: start()/stop() pattern with idempotency

## Build & Quality
```sh
poetry run ruff check .          # Lint (0 errors)
poetry run ruff format .         # Format (line-length 100, double quotes)
poetry run mypy src/             # Typecheck (strict)
poetry run pytest -k "not test_stop_during_run"  # 443 tests pass
```
