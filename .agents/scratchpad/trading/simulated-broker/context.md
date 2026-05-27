# Simulated Broker — Context

## Project State
- Python 3.12+ trading platform, Poetry, asyncio event loop
- 335 tests across 17 test files
- All core infrastructure implemented (event bus, journal, config, logging)
- All broker connectivity implemented (IBKRClient, MarketDataFeed, BrokerAdapter)
- Persistence (DatabaseManager, models, Alembic), Portfolio (PositionManager) done
- Strategy framework (base, loader, SMA crossover, mean reversion) done
- Risk Engine, Execution Engine, Replay Engine all implemented

## What We're Building
**Simulated Broker** — a drop-in replacement for `BrokerAdapter` that simulates order execution without IBKR. Enables full backtesting by replicating the order lifecycle locally.

## Existing Patterns to Follow

### BrokerAdapter (`broker/order_management.py`)
- Constructor takes `(ib: Any, event_bus: EventBus)`
- `start()`/`stop()` lifecycle with subscription management
- Subscribes to `OrderRequestedEvent`, emits `OrderSubmittedEvent`/`OrderFilledEvent`
- Uses `_subscribe_to_*` pattern returning unsubscribe lambdas
- Stores active trades in `_trades` dict

### Event Flow for Orders
```
OrderRequestedEvent → BrokerAdapter → OrderSubmittedEvent → OrderFilledEvent
```

### PositionManager (`portfolio/position.py`)
- Subscribes to `OrderFilledEvent` to track positions
- Computes avg cost, realized/unrealized PnL
- Emits `PositionOpenedEvent`/`PositionClosedEvent`/`PnLUpdatedEvent`/`PositionUpdate`

### ExecutionEngine (`execution/engine.py`)
- Subscribes to `SignalApprovedEvent`
- Calls `SizingEngine.compute_size()` for final quantity
- Publishes `OrderRequestedEvent`

### ReplayEngine (`replay/engine.py`)
- Loads historical `BarCloseEvent` list
- Publishes them in order at accelerated speed
- Uses `ReplayClock` for time management

## Key Design Decisions

1. **SimulatedBroker lives in `replay/simulated_broker.py`** — it's a backtesting component, not a live broker component
2. **Must implement the same event contract as BrokerAdapter** — so PortfolioManager works identically in backtest
3. **Fill models**: market orders fill at next available price, limit orders if price touches
4. **Configurable**: slippage (bps), commission (fixed per trade), fill latency

## Dependencies
- `EventBus` from `trading_platform.events.bus`
- `OrderRequestedEvent`, `OrderSubmittedEvent`, `OrderFilledEvent`, `OrderCancelledEvent`, `OrderStatusChangedEvent` from `event_types`
- `BarCloseEvent`, `MarketTickEvent` for price source

## File Layout
- Implementation: `src/trading_platform/replay/simulated_broker.py`
- Tests: `tests/test_simulated_broker.py`
