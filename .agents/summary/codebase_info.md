# Codebase Information

## Basic Metadata

| Attribute | Value |
|---|---|
| Project Name | trading-platform |
| Description | Event-driven modular trading platform for Interactive Brokers |
| Language | Python 3.12+ |
| Package Manager | Poetry |
| Build System | poetry-core |
| Test Framework | pytest 8+ with pytest-asyncio |
| Linter | ruff 0.7+ |
| Formatter | ruff (line-length 100, double quotes) |
| Type Checker | mypy (strict mode) |
| Pre-commit | ruff, ruff-format, mypy, trailing-whitespace, end-of-file-fixer, YAML/JSON checks |

## Source Overview

```
src/trading_platform/
  app/          — Config models, bootstrap, entry point
  broker/       — IBKR connection manager, market data feed
  events/       — Event types, priority event bus, SQLite journal
  monitoring/   — structlog setup
  execution/    — (stub)
  persistence/  — (stub)
  portfolio/    — (stub)
  replay/       — (stub)
  risk/         — (stub)
  strategies/   — (stub)
tests/          — 127 tests across 9 files
```

## Key Stats

| Metric | Value |
|---|---|
| Source files | 13 (non-stub) + 6 stubs |
| Test files | 9 (8 with tests) |
| Total tests | 127 |
| Event types | 25 concrete + BaseEvent |
| External dependencies | 7 runtime + 6 dev |
| Empty stub modules | 6 |
| Commits | 7 on main |
