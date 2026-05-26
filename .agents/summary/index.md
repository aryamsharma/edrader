# Codebase Knowledge Index

> Primary entry point for AI assistants. Contains metadata about each documentation file to help locate relevant information efficiently.

## How to Use This Index

1. Start here to understand what information is available and where
2. Consult specific files for detailed content on a topic
3. Use the consolidated `AGENTS.md` (in repo root) for a condensed assistant guide

## Document Map

| File | Purpose | Key Sections |
|---|---|---|
| `architecture.md` | System architecture, design patterns, runtime model | Event-driven architecture, modular monolith, async event loop, priority dispatch |
| `components.md` | Major components and their responsibilities | EventBus, EventJournal, IBKRClient, MarketDataFeed, Application |
| `interfaces.md` | APIs, interfaces, integration points | EventBus pub/sub, ib_insync wrapper, config loading, logging API |
| `data_models.md` | Data structures, events, config models | BaseEvent hierarchy, 25 event types, pydantic configs, SQLAlchemy model |
| `workflows.md` | Key processes and workflows | Connection lifecycle, market data flow, event dispatch, reconnect, TDD cycle |
| `dependencies.md` | External dependencies and usage | pydantic, structlog, ib_insync, SQLAlchemy, pyyaml, dev tooling |
| `codebase_info.md` | Basic codebase metadata | File counts, test stats, language versions, tooling |

## Quick Reference by Question Type

| Question | File to Consult |
|---|---|
| "How does the event system work?" | `architecture.md`, `components.md` (EventBus section), `data_models.md` (BaseEvent) |
| "What events exist?" | `data_models.md` (25 event types table) |
| "How do I add a new event type?" | `data_models.md` (BaseEvent pattern), `interfaces.md` (serialization) |
| "How does IBKR connectivity work?" | `components.md` (IBKRClient, MarketDataFeed) |
| "What's the testing setup?" | `codebase_info.md` (tooling), `components.md` (test patterns) |
| "How do I run lint/typecheck/tests?" | `codebase_info.md` (commands), `dependencies.md` |
| "What are the architecture rules?" | `architecture.md` (design principles, constraints) |
| "What's the project structure?" | `codebase_info.md` (source overview) |
| "How do I implement Phase 2.3?" | `components.md` (stub modules), `architecture.md` (planned structure) |
| "What are the commit conventions?" | `workflows.md` (commit conventions) |

## Cross-References

- `architecture.md` references `components.md` for detailed component descriptions
- `components.md` references `interfaces.md` for public APIs
- `data_models.md` references `interfaces.md` for serialization contracts
- `workflows.md` references `components.md` and `architecture.md` for context
- `dependencies.md` references all other files for usage context
