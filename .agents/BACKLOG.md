# Backlog

## Consider: circular buffer instead of `asyncio.Queue` in PriorityQueue

Replace the two `asyncio.Queue` instances (backed by `collections.deque`) with fixed-size ring buffers. Hypothesis: better cache locality and pre-allocated memory reduce latency in the async dispatch path.

**Caveat**: Only affects async (live) mode. Sync mode (backtest) bypasses the queue entirely.

**Likely outcome**: Marginal win at best — `collections.deque` is already a C-level O(1) data structure, and the real async latency is in subscriber dispatch with `wait_for` and external I/O.

## Benchmark: `asyncio.PriorityQueue` vs custom dual-queue PriorityQueue

Implement an optional alternative `PriorityQueue` using `asyncio.PriorityQueue` internally (with `(priority.value, event)` tuples) and benchmark it against the current dual-queue implementation.

### Approach

- Add a `use_async_priority_queue` flag to `EventBus.__init__()`
- When set, construct an `asyncio.PriorityQueue` instead of the custom `PriorityQueue`
- Wrap it in a compatible interface (`put`, `get`, `task_done`, `qsize`, `join`)
- Compare latency profile under backtest load

### Key questions to answer

1. Does the `get_nowait()` fast path in the current implementation actually matter, or does `asyncio.PriorityQueue`'s `heapq`-based `get()` perform similarly?
2. Does the 1ms `wait_for` fallback in the current implementation add measurable latency?
3. Is the dual-queue `join()` behavior necessary, or would a single-heap approach work just as well?
4. Profile under both live (async) and backtest (sync_mode) dispatch patterns.

### See Also

- `src/edrader/events/bus.py:37` — current `PriorityQueue` implementation
- The 8.4× backtest speedup (22s vs 184s) relies partly on the fast-path `get_nowait()`

## Stale state in async dispatch (RiskEngine false approvals) — RESOLVED

**Status**: Implemented Option C (RiskEngine queries PositionManager directly) + subscriber ordering fix (broker registered before strategies for BarCloseEvent).

**Observed**: Async-mode benchmark approved 481 signals that sync-mode correctly rejected (SignalRejectedEvent + RiskViolationEvent). Sync is the only correct mode for backtesting.

**Root cause**: The event queue decouples causally-related events. The cascade for one bar:
```
BarCloseEvent → Strategy → SignalGeneratedEvent
  → RiskEngine → SignalApprovedEvent
    → ExecutionEngine → OrderRequestedEvent
      → SimulatedBroker → OrderFilledEvent
        → PositionManager → ExposureUpdatedEvent
```

In sync mode, this completes before the next bar. In async mode, all events share the same FIFO queue (all `priority=NORMAL`). When events are published faster than they're drained, the queue fills with BarCloseEvents ahead of downstream events.

**Fix — two parts:**

1. **Option C: RiskEngine queries PositionManager directly** — `RiskEngine.__init__()` now takes a `PositionManager` reference. On `_on_signal`, calls `pm.positions`, `pm.equity`, `pm.leverage`, `pm.total_realized_pnl` instead of cached values. Removed `_positions`, `_exposure`, `_equity`, `_daily_realized_pnl` caches and their subscribers (`_on_fill`, `_on_exposure_update`).

2. **Subscriber ordering** — SimulatedBroker registers its `BarCloseEvent` handler before strategies, so pending orders from the previous bar are filled before the next bar triggers a signal. Fixed in `scripts/compare_sync_async.py` and `scripts/loadtest.py` (already correct in `scripts/backtest.py` and `src/edrader/app/bootstrap.py`).

**Remaining limitation**: Under firehose publishing (140k events published back-to-back), async mode still shows discrepancies because the broker's BarCloseEvent handler is queued behind the strategy's signal cascade. This is a backtest-only artifact — live trading has wall-clock spacing between bars, so the queue always drains between events.

**Live trading risk**: Resolved for bar-frequency strategies. Tick-frequency strategies still have a stale-state window during the IBKR round-trip (10-100ms), but this is a fundamental limitation of the event-driven architecture, not a caching bug.

### Files
- `src/edrader/risk/engine.py` — RiskEngine now queries PositionManager directly (no cached state)
- `src/edrader/portfolio/position.py` — PositionManager provides live state via `positions`, `equity`, `exposure()`, `total_realized_pnl`
- `scripts/compare_sync_async.py` — benchmark reproducing the stale-state issue (subscriber order fixed)

## SBE for inter-service messaging

**Idea**: Replace in-memory event bus + dataclass events with SBE-encoded messages over Redis (or Aeron) for a distributed service architecture. Each service (RiskEngine, ExecutionEngine, PositionManager) would own its state and expose it via query — no cached copies to go stale.

### Python SBE library options

| Library | Approach | Performance | Multi-lang | Schema | Status |
|---------|----------|-------------|-------------|--------|--------|
| **protowire-python** ⭐ | C++ nanobind FFI | 382ns unmarshal, 236ns marshal (C++); ~1µs (Go) | Go, Rust, Java, TS, C#, Swift | `.proto` + SBE annotations | v1.0.0 (May 2026), wheels for macOS ARM/Linux/Windows |
| **`sbe` (kizzx2/sbe-python)** | Pure Python | Adequate for non-tick paths | Python only | FIX SBE XML | v0.4.3 (Dec 2024), stable |
| **sbedecoder** | Dynamic parser gen | Not optimized (post-trade analytics) | Python only | FIX SBE XML | Stable, CME MDP3 focused |
| **sbe-codegen** (rust) | Rust → maturin Python | Rust-tier | Rust + Python | FIX SBE XML | v0.1.0 (Oct 2024), early |
| **IronSBE** | Full Rust impl | 1ns decode, 3ns encode | Rust only (codegen) | FIX SBE XML | v0.1 (Jan 2026), active |

### Recommendation: protowire-python
- One `.proto` schema defines all domain events (SignalGeneratedEvent, OrderFilledEvent, ExposureUpdatedEvent, etc.)
- SBE tier gives sub-microsecond binary encode/decode with zero-alloc `view()` reads
- Same schema works across languages — RiskEngine could be rewritten in Go/Rust later without changing wire format
- `sbe.Codec.from_message(OrderType)` → `marshal()` / `unmarshal()` / `view()`
- Wire-compatible with FIX SBE 1.0

### Next steps if pursued
1. Prototype an SBE schema for core event types (SignalGeneratedEvent, OrderFilledEvent, ExposureUpdatedEvent)
2. Benchmark protowire-sbe encode/decode vs current dataclass + `to_dict()`/`from_dict()` serialization
3. Design service boundaries: what state does each service own, what queries does it expose?
4. Evaluate transport: Redis pub/sub vs Aeron vs nanomsg for inter-service communication

## Performance improvements

Current backtest: ~22s for 140k events (sync mode, 8.4× speedup from baseline).

### High Impact

**1. ~~Replace `uuid.uuid4()` with monotonic counter for `event_id`~~** ✅ DONE
- Replaced with `{hostname}-{pid}-{counter}` format — globally unique, zero syscalls per event

**2. Eliminate no-subscriber events** (multiple files)
- `OrderStatusChangedEvent`: 0 subscribers (published by `simulated_broker.py:123`)
- `PositionOpenedEvent`: 0 subscribers (published by `position.py:145`)
- `PnLUpdatedEvent`: 0 subscribers (published by `position.py:163`)
- `PositionUpdate`: 0 subscribers (published by `position.py:297`)
- Options:
  - a) Skip publish if no subscribers via `EventBus._handlers_for()` check
  - b) Remove the events entirely (but they may be needed by persistent/journal/wildcard subscribers)
  - c) Defer publish to lazy/on-demand when a subscriber registers

**3. Merge SimulatedBroker's 3-event fill into 1** (`simulated_broker.py:107-140`)
- Current: `_fill_order()` publishes `OrderSubmittedEvent` + `OrderStatusChangedEvent` + `OrderFilledEvent`
- `OrderStatusChangedEvent` has zero subscribers; `OrderSubmittedEvent` has one (ExecutionEngine)
- Could collapse into a single `OrderFilledEvent` and move ExecutionEngine's `_on_submitted` logic (tracking `_active_orders`) into `_on_filled`
- Impact: -2 events per fill (if 500 fills, that's 1000 fewer events)

### Medium Impact

**4. Replace `datetime.now(UTC)` with deferred/lazy timestamp** (`event_types.py:20`)
- Every event construction calls `datetime.now(UTC)` as field default
- Strategy-emitted events during backtest get wall-clock time instead of backtest clock time — correctness bug + syscall
- Fix: make timestamp lazy (e.g. `None` until first access), or inject clock from EventBus
- Impact: every event, but `datetime.now()` is fast (~0.3µs) — mainly a correctness fix

**5. PositionManager._compute_unrealized_pnl is O(n) per update** (`position.py:269-276`)
- Iterates ALL positions to compute total unrealized PnL
- Called from `process_fill` and `_on_tick` — every fill/tick pays O(n)
- Fix: maintain a running total, update incrementally when a single position changes

**6. Remove redundant `assert isinstance()` in handlers**
- Every `_on_signal`, `_on_fill`, `_on_tick`, etc. starts with `assert isinstance(event, SpecificType)`
- The subscription already guarantees the type — this is pure overhead

### Low Impact

**7. MarketTickEvent filtered dispatch** (risk/engine.py, execution/engine.py, position.py, simulated_broker.py)
- Every tick dispatches to 4 subscribers even when idle (no positions, no held orders)
- Each handler does a cheap check (e.g. `if symbol in self._positions`) but still pays dispatch overhead
- Could add per-symbol subscriber filters

**8. Pre-allocate EventBus handler dispatch table** (`bus.py:118-126`)
- `_handlers_for()` creates a new merged list on cache miss; cache is invalidated on every subscribe/unsubscribe
- Since subscribers are registered at startup and never change during backtest, cache stays warm
- Already optimized via `_handler_cache` — minimal impact

### Files
- `src/edrader/events/event_types.py:19` — uuid4 + datetime.now per-event overhead
- `src/edrader/replay/simulated_broker.py:107-140` — 3-event fill cascade
- `src/edrader/portfolio/position.py:269-276` — O(n) unrealized PnL
- `src/edrader/events/bus.py:174-209` — _dispatch overhead
- `src/edrader/risk/engine.py` — isinstance checks in every handler
- `src/edrader/execution/engine.py` — isinstance checks in every handler

## PE Review: Additional findings

Items below are from a principal engineer performance review, excluding recommendations already captured above.

### Medium Impact (new)

**9. PositionManager recomputes ExposureSnapshot from scratch on every tick** (`position.py:282-315`)
- `_on_tick` calls `_publish_exposure()` which calls `self.exposure()` — iterates ALL positions (O(n))
- Then `self.leverage` calls `self.exposure()` again — double iteration per tick
- For 50 positions at 250ms tick intervals: 400 position iterations/second just for exposure
- Fix: cache `_cached_snapshot: ExposureSnapshot` and update incrementally when position changes; skip recompute on ticks that don't affect position

**10. EventJournal builds ORM objects then converts to dicts for insert** (`journal.py:66-105`)
- `append()` creates `EventRecord` ORM objects in buffer
- `_flush_batch` converts them back to dicts for raw SQL `executemany`
- Two representations per row before reaching SQLite
- Fix: buffer raw dicts instead of ORM objects; use ORM only for `replay()` queries where the query API justifies it

### Low Impact (new)

**11. ReplayEngine._wait_for_next chunked sleep loop** (`engine.py:111-113`)
- Sleeps in 0.1s chunks with a while loop: `while adjusted > 0: chunk = min(adjusted, 0.1); await asyncio.sleep(chunk)`
- At speed 1.0: 10 async wakeups per second for the entire replay duration
- Fix: single `await asyncio.sleep(adjusted)` — `asyncio.sleep` handles arbitrary durations efficiently

**12. PositionManager._persist_position SELECT before UPSERT** (`position.py:317-343`)
- Does `session.query(PositionRecord).filter_by(symbol=symbol).first()` then INSERT or UPDATE
- SQLite supports `INSERT ... ON CONFLICT (symbol) DO UPDATE SET ...` which eliminates the round-trip
- Only matters when a DB is configured (guarded by `if self._db_manager is None: return`)

## EventBus publish_rate metric — rationale and safe upper bound

**Added**: `DispatchMetrics.snapshot()` now includes `publish_rate` (events/sec), computed as the delta between consecutive `snapshot()` calls. Included in `RuntimeSnapshot` via `MetricsCollector.snapshot()`.

**Rationale**: At live tick rates (~200 ev/s for a few liquid symbols), the pipeline drains 40× faster than events arrive. But during bursty periods (e.g., market open, news events, 10+ symbols), the aggregate rate can spike to 1,000+ ticks/sec. Without a rate metric, operators cannot distinguish normal throughput from queue back-pressure.

**Safe upper bound from stale-state analysis**:
- Pipeline drain rate: ~8,000 ev/s (sync-mode 140k/2.67s ÷ 6.3µs queue overhead). Practical async drain: ~6,000 ev/s.
- **WARN threshold (500 ev/s)**: Aggregate tick rate exceeds 50% of pipeline capacity. Queue may build during bursts.
- **CRIT threshold (800 ev/s)**: Queue growth likely during sustained periods. Stale-state window widens.
- **HARD LIMIT (1,000 ev/s)**: Subscription rejected. At this rate, async pipeline cannot drain fast enough to prevent stale-state violations for tick-frequency strategies.

**Proactive alarming**: `MarketDataFeed.subscribe_symbol()` now accepts an `expected_tick_rate` parameter (default 20/sec, adjust per symbol — e.g., SPY=50, AAPL=30, BRK.B=5). On each `subscribe_symbol()` call, the cumulative expected rate is checked against the thresholds above, and appropriate warnings are logged. At HARD_LIMIT, subscription is refused with `RuntimeError`.

### Observations (no action required)

- **MeanReversionStrategy._compute_stats O(n)** per bar — fine for current window sizes (20-30). VWAP already uses incremental approach, which is the correct pattern.
- **MetricsCollector subscribe_all** catches every event — useful observability in live, pure overhead in backtest. Could disable during replay.
- **Strategy stats are correct for current usage** — Welford's online algorithm not worth the complexity at these window sizes.
