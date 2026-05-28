# Documentation Review Notes

## Consistency Check
- **Event type count:** 27 concrete event types. Consistent across all docs.
- **Test count:** 443 tests across 22 files (1 flaky excluded: `test_stop_during_run`). Consistent with actual results.
- **Module count:** 11 module directories under `src/edrader/`. Consistent.
- **File references:** All component locations verified against actual file paths. Package name fixed from `src/trading_platform/` → `src/edrader/`.
- **Test file count:** 22 test files + `conftest.py` + `__init__.py`.

## Completeness Check
- **Architecture:** Fully covered — event-driven design, component lifecycle, IBKR isolation boundary, live/backtest parity, priority queue dispatch
- **Components:** All components documented with file locations, event subscriptions, subscribers, and key features. Includes recent additions: `subscriber_timeout`, `task_error_logger`, ATR-based sizing, consolidated PnL, CSV error handling.
- **Interfaces:** Complete event catalog with publishers and subscribers; component registration pattern documented. Updated subscriber lists for `ExecutionEngine` and `ExposureUpdatedEvent`.
- **Data models:** All domain dataclasses (`Position`, `ExposureSnapshot`, `BacktestMetrics`, `PendingOrder`, `CompletedOrder`, `RuntimeSnapshot`, `DispatchMetrics`), DB models (5 tables), config models, and serialization format covered.
- **Workflows:** Signal→fill pipeline, connection lifecycle, market data flow, position management (state transitions with partial covers), simulated order execution, backtest metrics computation, risk check pipeline, replay engine flow, alert flow with cooldown and heartbeat.
- **Dependencies:** All runtime and dev dependencies with usage patterns, version constraints, and known typing quirks.

## Gaps Identified
1. **No deployment/operations docs:** The platform has no containerization, CI/CD, or production deployment configuration. Appropriate for development stage.
2. **No external API docs:** The platform intentionally has no REST/API layer — the EventBus is the sole interface.
3. **`_on_filled` in ExecutionEngine:** Subscribed but unreferenced in tests — dead code per the subscription wiring check.
4. **4 event types never published:** `MarketOpenEvent`, `MarketCloseEvent`, `StrategyErrorEvent`, `AccountSummaryUpdate` are defined but never emitted.

## Recommendations
1. Keep AGENTS.md concise — current version is well-balanced for AI assistant navigation.
2. The summary files provide sufficient depth for comprehensive understanding.
3. If new event types are added, update the count in both AGENTS.md and codebase_info.md.
4. Move test count to a single source of truth (e.g., `pyproject.toml` comment) to avoid drift across 8+ doc files.
