# Principal Engineer Code Review

**Date:** 2026-05-28 (updated 2026-05-28)
**Scope:** All 25 source files under `src/edrader/` (~3,910 lines)
**Reviewer:** opencode (principal engineer mode)

---

## Critical Issues

### 1. Hardcoded equity in ExecutionEngine ✅

`execution/engine.py:124` — `equity = 100_000.0` was hardcoded instead of coming from `PositionManager.equity`. All order sizing used a stale constant.

**Fix applied:** `ExecutionEngine` now subscribes to `ExposureUpdatedEvent` via `_subscribe_exposure()` in `execution/engine.py:228`. The `_on_exposure_update` handler updates `self._equity` from live event data. Initialized to `100_000.0` as fallback until first event arrives. Tested in `test_exposure_update_tracks_equity`.

### 2. EventBus dispatch loop is a single-point failure ✅

`events/bus.py` — one asyncio task dispatches all events sequentially, with no protection against hung handlers.

**Fix applied:** Added `subscriber_timeout` parameter (default 5.0s) to `EventBus` constructor. Each handler is wrapped in `asyncio.wait_for()` in `_dispatch()`. `TimeoutError` is caught, logged with handler name and event details, and tracked in `DispatchMetrics`. Tested in `test_slow_handler_timeout` and `test_slow_handler_does_not_block_other_events`.

### 3. Fire-and-forget tasks in sync contexts ✅

`broker/ibkr_client.py:92` and `broker/market_data.py:195` — `asyncio.create_task()` discards exceptions from background tasks.

**Fix applied:** Extracted a shared `task_error_logger()` factory into `broker/__init__.py` that returns a `done_callback` logging any `Exception` and swallowing `CancelledError`. Wired to both `IBKRClient._on_disconnected` and `MarketDataFeed._on_pending_tickers`. Duplicate definitions eliminated. Tested in `tests/test_broker.py`. Tasks with unknown symbols or failed publishes now log `ibkr_background_task_failed` / `market_data_background_task_failed` instead of silently failing.

---

## Design Issues

### 4. Sync SQLAlchemy in async event loop

`events/journal.py` — `EventJournal.append()` runs synchronous SQLite inserts inside the async dispatch loop. With `subscribe_all`, every event triggers a DB write. Under high-frequency tick data this will become a bottleneck.

**Options:** aiosqlite driver, batch writes (flush every N events on a timer), or offload to a `run_in_executor` thread.

### 5. Four event types are never published

| Event | Status |
|---|---|
| `MarketOpenEvent` | Defined but never published |
| `MarketCloseEvent` | Defined but never published |
| `StrategyErrorEvent` | Defined but never published |
| `AccountSummaryUpdate` | Defined but never published |

Either wire them up or remove them. Dead types add cognitive load.

### 6. MetricsCollector polls instead of subscribing

`monitoring/metrics.py` — polls `EventBus.metrics.snapshot()` on a timer rather than subscribing to events. This means it can miss spikes in throughput between polls.

**Fix:** Subscribe to all events and count them, or use a ring buffer updated by the dispatch loop directly.

### 7. `db_manager: Any` everywhere

Every component that touches persistence takes `db_manager: Any` instead of `DatabaseManager`. This defeats type checking. Tests pass `None`, which works, but mypy can't catch mistakes.

**Fix:** Use `DatabaseManager | None` as the type annotation.

### 8. `max_retries` is a dead parameter in ExecutionEngine

`execution/engine.py:33` — stored as `self._max_retries` but never used anywhere. Either implement retry logic or remove the parameter.

---

## Code Quality Issues

### 9. Duplicate PnL computation in PositionManager ✅

`portfolio/position.py:71` (`total_unrealized_pnl`) iterates all positions; `_on_tick` at line 284 computes `_unrealized_pnl` again within a loop. The property is never called during tick processing, but this is two code paths computing the same thing with slightly different logic.

**Fix applied:** Added `_compute_unrealized_pnl()` returning `(total, per_symbol)` — single pass used by both `total_unrealized_pnl` property and `total_pnl` property. `_on_tick` and `process_fill` compute equity once and pass it to `_publish_exposure(equity=...)` to avoid triggering the property chain (`equity → total_pnl → total_unrealized_pnl`) a second time.

### 10. ReplayClock speed=0 causes division by zero ✅

`replay/engine.py:106` — the sleep calculation `adjusted = delta / speed` will divide by zero if `speed` is set to 0. The property setter validates `speed > 0`, but division had no runtime guard.

**Fix applied:** Division guarded with `max(self._clock.speed, 0.001)`. Also `ReplayClock.reset()` now uses the property setter (`self.speed = 1.0`) instead of direct `_speed` assignment, ensuring validation runs on all write paths.

### 11. HistoricalFeed CSV parsing is fragile ✅

`replay/historical_feed.py` — `load_csv()` didn't handle file open errors (permissions, missing file). Row-level issues (empty files, inconsistent columns, missing dates, non-numeric prices) were already handled by `csv.DictReader` defaults and the existing try/except in the row loop.

**Fix applied:** Wrapped `_read_csv()` call in `try/except OSError` with `logger.error("historical_feed_read_failed", ...)` before re-raising. Missing file test already existed and continues to expect `FileNotFoundError`.

### 12. SizingEngine.volatility is a stub ✅

`execution/sizing.py` — the `volatility` method just returned `suggested_size`. It didn't use `_atr_cache` at all.

**Fix applied:** `_volatility_size` now uses `_atr_cache[symbol]`. With equity available: `risk_amount = equity * percent_equity_fraction` → `size = risk_amount / atr`. Without equity: scales `suggested_size` inversely with `atr / price`. Added `symbol` parameter to `compute_size()` and wired it from `ExecutionEngine._on_approved_signal`. Falls back to `suggested_size` when ATR data is missing.

---

## Testing Gaps

### 13. Order lifecycle cleanup — improved ⚠️

`_on_filled` is now subscribed and `_on_cancelled` cleans up `_active_orders`. Existing tests verify subscription registration, but no test directly asserts that `_active_orders` is empty after processing a fill or cancellation event.

### 14. `test_stop_during_run` flakiness ✅

**Root cause:** `_wait_for_next` called `await asyncio.sleep(60000)` with no `_running` check. `stop()` set the flag but couldn't interrupt the sleep. The test hung for ~16.7 hours.

**Fix applied:** `_wait_for_next` now polls `self._running` in 0.1s chunks via a `while` loop. `stop()` sets `_running = False` and the sleep exits within 100ms. Verified: 20/20 passes at ~0.13s each.

### New coverage added (8 tests, plus 4 existing tests updated)

| Test file | Tests | Coverage |
|---|---|---|
| `tests/test_broker.py` (new) | 4 | `task_error_logger` — success, CancelledError, exception logging, non-propagation |
| `tests/test_event_bus.py` | 2 | `subscriber_timeout` — timeout metrics, continued processing after timeout |
| `tests/test_execution.py` | 2 | `ExposureUpdatedEvent` — subscription registration, equity update |

Existing tests cover items 9–12: `test_total_pnl_combines_realized_and_unrealized`, `test_unrealized_pnl_updates_on_tick`, `test_equity_includes_pnl`, `test_speed_must_be_positive`, `test_speed_setter`, `test_load_csv_missing_file`, `test_load_csv_malformed_row_skipped`, `test_volatility_sizing_falls_back_to_suggested`, `test_update_atr`. No test changes needed — all 443 pass.

---

## What's Well Done

| Area | Why It's Good |
|---|---|
| **Event isolation** | 27 typed frozen dataclasses with `to_dict()/from_dict()` — clean serialization, no proto/avro dependency, easy to test |
| **Component lifecycle** | `start()/stop()` with idempotency guards and stored unsub callables — consistent across all 10+ components |
| **Live/backtest parity** | Same code path for live and backtest — only data source and clock differ. The hardest thing to get right |
| **RiskEngine kill switch** | `_halted` flag gates all signals, `TradingHaltedEvent` propagates to alerting — clean and auditable |
| **PositionManager fill logic** | Partial covers (both directions), avg_cost averaging, realized PnL from covering trades — correct accounting in ~40 lines |
| **Test fixture pattern** | `collected_events` with `subscribe_all + drain()` is simple and effective |
| **Typing discipline** | 27 event types with no `ib_insync` type leakage outside `broker/` — the single biggest maintenance win |
