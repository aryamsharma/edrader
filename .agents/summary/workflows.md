# Workflows

## Live Trading Flow

```
1. Application.startup()
   ├── EventBus.start()           # creates _processing_task
   ├── Live components start:
   │   ├── IBKRClient.connect()  # connects to TWS/Gateway
   │   ├── MarketDataFeed.start()  # subscribes to IBKR market data (ticks + bars)
   │   └── BrokerAdapter.start()  # subscribes to OrderRequestedEvent
   ├── Monitoring components start:
   │   ├── RiskEngine.start()     # subscribes to SignalGeneratedEvent, fills, ticks, disconnect, exposure
   │   ├── ExecutionEngine.start()  # subscribes to SignalApprovedEvent, ticks, orders, exposure
   │   ├── PositionManager.start()  # subscribes to OrderFilledEvent, MarketTickEvent
   │   ├── MetricsCollector.start()  # subscribe_all for event counting
   │   └── AlertManager.start()    # subscribes to system events (disconnect, risk, etc.)
   ├── EventJournal wired: subscribe_all → journal.append(event)
   ├── StrategyLoader.register("sma_crossover", ...), register("mean_reversion", ...)
   └── Strategies start:
       ├── sma_crossover.start()   # subscribes to BarCloseEvent
       └── mean_reversion.start()  # subscribes to BarCloseEvent

2. MarketDataFeed receives tick from IBKR
   → publish(MarketTickEvent, priority=HIGH)
   → EventBus queues → dispatch task processes

3. MarketDataFeed detects bar close
   → publish(BarCloseEvent, priority=NORMAL)

4. Strategy.on_event(BarCloseEvent)
   → compute indicators (SMA, z-score, etc.)
   → if signal triggered: emit_signal(symbol, side, confidence, size)
   → publish(SignalGeneratedEvent)

5. RiskEngine subscriber:
   → _on_signal(SignalGeneratedEvent)
   → 6 checks (max_position_size, daily_loss, leverage, symbol_exposure, concurrent, stale_market)
   → if kill_switch active → reject("kill_switch_active")
   → if any check fails → reject(reason) + publish(RiskViolationEvent)
   → if all pass → approve → publish(SignalApprovedEvent)

6. ExecutionEngine subscriber:
   → _on_approved_signal(SignalApprovedEvent)
   → throttle check: if symbol cooldown active, return (publish empty OrderSubmittedEvent)
   → sizing = SizingEngine.compute_size(suggested_size, price, equity, symbol)
   → if sizing > 0: publish(OrderRequestedEvent)
   → schedule retry task (if max_retries > 0)

7. BrokerAdapter subscriber:
   → _on_order_request(OrderRequestedEvent)
   → place order via IBKR
   → publish(OrderSubmittedEvent, OrderStatusChangedEvent, OrderFilledEvent)

8. PositionManager subscriber:
   → process_fill(OrderFilledEvent)
   → update Position(avg_cost, realized_pnl)
   → publish(PositionOpenedEvent / PositionClosedEvent, PnLUpdatedEvent)
   → publish(ExposureUpdatedEvent)
   → optionally persist to db_manager

9. Application.shutdown():
   → stop strategies
   → stop monitoring components (reverse order)
   → stop live components (reverse order)
   → journal.close()
   → EventBus.stop()
```

## Backtest Flow (via `scripts/backtest.py`)

```
1. setup_logging("WARNING")  # default; --verbose → "DEBUG"
2. EventBus.start()

3. (Optional) EventJournal(database_url="sqlite:///tmp.db", batch_size=0, fast_mode=True)
   → subscribe_all → journal.append(event)

4. Create pipeline components:
   ├── SmaCrossoverStrategy("sma_crossover", bus, fast_window=10, slow_window=30)
   ├── MeanReversionStrategy("mean_reversion", bus, window=20, entry_z=2.0, exit_z=0.5)
   │   (or VwapReversionStrategy("vwap_reversion", bus) for --tick mode)
   ├── RiskEngine(bus, max_position_size=500, max_daily_loss=50_000, max_concurrent=50)
   ├── ExecutionEngine(bus, default_order_type="MKT", throttle_delay=0.0, max_retries=0)
   ├── SimulatedBroker(bus, slippage_bps=5.0, commission_per_trade=1.50)
   ├── PositionManager(bus)
   └── MetricsEngine(bus, initial_capital=100_000.0)

5. Start all components (risk → exec → broker → pm → metrics)
6. Start all strategies

7. HistoricalFeed: load_csv(path, symbol) or load_tick_csv(path, symbol)
   → ReplayClock.speed = 1_000_000
   → ReplayEngine.load_events(events)

8. engine.run():
   ├── event_bus.sync_mode = True
   ├── for each event (sorted by timestamp):
   │   ├── clock.set_time(event.timestamp)
   │   ├── event_bus.publish(event)  # sync dispatch to all subscribers
   │   │   ├── strategy.on_event() → emit_signal() → publish(SignalGeneratedEvent)
   │   │   │   → sync dispatch → RiskEngine → SignalApprovedEvent → ExecutionEngine
   │   │   │   → OrderRequestedEvent → SimulatedBroker → OrderFilledEvent → PositionManager
   │   │   └── (journal.append() if enabled)
   │   └── _wait_for_next(delta / speed); skip if < 1ms
   └── finally: event_bus.sync_mode = False

9. engine.run() completes
10. bus.drain()  # finish any remaining async events
11. Stop all components (reverse order)
12. Journal.flush() + close()
13. metrics.compute() → BacktestMetrics printed
```

## Kill Switch / Halt Flow

```
RiskEngine discovers condition (manual activate_kill_switch or BrokerDisconnectedEvent):
  → self._kill_switch = True
  → if from disconnect: publish(TradingHaltedEvent)

Subsequent SignalGeneratedEvent:
  → RiskEngine._on_signal() → self._kill_switch is True
  → publish(SignalRejectedEvent(reason="kill_switch_active"))
  → NO SignalApprovedEvent routed to ExecutionEngine

Manual recovery:
  → risk.deactivate_kill_switch()
  → signals flow normally again
```

## Journal Persistence Flow

```
Live mode:
  EventJournal(database_url="sqlite:///data/trading.db", batch_size=500, fast_mode=False)
  → subscribe_all → journal.append(event)
    → _sequence += 1
    → serialize event → json.dumps(to_dict())
    → append to `_buffer` list
    → if len(buffer) >= 500: flush batch via executemany
  → close(): flush remaining, engine.dispose()

Backtest mode:
  EventJournal(database_url, batch_size=0, fast_mode=True)
  → PRAGMA synchronous=OFF, journal_mode=MEMORY, cache_size=-64000
  → append() buffers all events (batch_size=0 means no auto-flush)
  → after replay completes: flush() → single bulk executemany of all buffered rows
  → close()

Replay from journal:
  journal.replay(event_types=[BarCloseEvent], since_sequence=0, limit=1000)
  → Session.query(EventRecord).filter(sequence > since_sequence)
  → if event_types: filter by event_type in type_names
  → order_by(sequence.asc()), optional limit
  → for each record: json.loads(payload) → BaseEvent.from_dict(payload)
  → return list[BaseEvent]
```

## Loadtest Flow (via `scripts/loadtest.py`)

Step-by-step subscriber addition to measure latency scaling:

```
1. HistoricalFeed.load_csv(csv, symbol="TEST") → N events
2. EventBus(max_queue_size=1_000_000)
3. Add subscribers one by one, measuring N-publish + drain time:
   Step 1: SmaCrossoverStrategy
   Step 2: RiskEngine
   Step 3: ExecutionEngine
   Step 4: SimulatedBroker
   Step 5: PositionManager
   Step 6: MetricsEngine
   Step 7: subscribe_all mem_journal (event counter)
4. For each ev: bus.publish(ev) → measure publish time
5. bus.drain() → measure drain time
6. Report: events by type, publish/drain/total time, ev/s
```

## Throttle and Retry Flow

```
ExecutionEngine._on_approved_signal(SignalApprovedEvent):
  → _throttle_remaining(symbol) = time.monotonic() - _last_order_time[symbol]
  → if remaining > 0:
      → publish(OrderSubmittedEvent(order_id=""))  # no-op signal
      → return (order not placed)

  → compute_size → publish(OrderRequestedEvent)
  → _last_order_time[symbol] = time.monotonic()
  → if max_retries > 0:
      → _pending_retries[key] = max_retries
      → create_task(_retry_pending_order(symbol, side, size, type))

  _retry_pending_order:
    → await sleep(2.0)
    → if key not in _pending_retries: return (order was submitted/filled)
    → if remaining <= 0: return
    → decrement remaining
    → publish(OrderRequestedEvent) again
```

## Simulated Fill Price Resolution

```
SimulatedBroker._on_order_request(OrderRequestedEvent):
  → price = _prices.get(symbol)
  → if order_type == "MKT":
      → if price: fill immediately at slippage-adjusted price
      → else: hold in _held_market_orders (fill on next bar/tick)
  → if order_type == "LMT" and limit_price:
      → if limit_crossed(side, price, limit_price): fill at limit_price
      → else: hold in _pending_orders

SimulatedBroker._on_bar_close(BarCloseEvent):
  → _prices[symbol] = event.close
  → _try_fill_held_orders(symbol, event.close)
    → fill all held MKT orders at this price
    → fill all LMT orders whose limit is now crossed

SimulatedBroker._on_tick(MarketTickEvent):
  → same as _on_bar_close but with event.price
```
