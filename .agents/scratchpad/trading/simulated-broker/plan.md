# Simulated Broker — Plan

## Test Strategy

### Test Classes
- `TestSimulatedBrokerLifecycle` — start/stop, subscription management
- `TestSimulatedBrokerMarketOrder` — market order fills using price source
- `TestSimulatedBrokerLimitOrder` — limit order fill logic
- `TestSimulatedBrokerCommissions` — commission deduction from fills
- `TestSimulatedBrokerSlippage` — slippage applied to fill price
- `TestSimulatedBrokerPriceSource` — BarCloseEvent vs MarketTickEvent pricing
- `TestSimulatedBrokerEdgeCases` — zero quantities, unknown symbols, no-price scenarios

### Test Scenarios
1. Initial state: not running, no active orders, prices empty
2. start() sets running, subscribes to OrderRequestedEvent and BarCloseEvent
3. stop() clears state, unsubscribes
4. start/stop idempotent
5. Market order BUY fills at current price, emits OrderSubmittedEvent + OrderFilledEvent
6. Market order SELL fills at current price
7. Market order with unknown symbol (no price) — order held until price arrives
8. Limit order BUY fills when price drops to limit
9. Limit order SELL fills when price rises to limit
10. Limit order stays open when price hasn't crossed
11. Commission per trade deducted from fill
12. Zero commission = no deduction
13. Slippage applied (BUY gets worse price, SELL gets worse price)
14. Zero slippage = exact price
15. BarCloseEvent provides price for fills
16. Multiple orders tracked independently
17. Order before start ignored (not running)
18. Fill at exact limit price
19. Price update triggers multiple pending limit orders

## Implementation Plan

### Architecture
```
SimulatedBroker (replay/simulated_broker.py)
  - subscribes to: OrderRequestedEvent, BarCloseEvent, MarketTickEvent
  - emits: OrderSubmittedEvent, OrderFilledEvent, OrderStatusChangedEvent, OrderCancelledEvent
  - tracks: pending orders (limit orders waiting for price), current prices
```

### Fill Model
- **Market orders**: fill immediately at last known price (or defer if no price known)
- **Limit orders**: stored in pending dict; on each BarCloseEvent/MarketTickEvent, check if limit is crossed
- **Slippage**: `slippage_bps` — BUY adds bps, SELL subtracts bps from fill price
- **Commission**: `commission_per_trade` — fixed amount subtracted per fill event
- **Order ID**: auto-generated UUID string

### Key Methods
- `_on_order_request(event)` — handle incoming order request
- `_on_bar_close(event)` — update prices, try pending limit orders
- `_on_tick(event)` — update prices, try pending limit orders
- `_fill_market_order(symbol, side, quantity, order_type, limit_price)` — immediate fill
- `_try_fill_limit_orders(symbol, price)` — check all pending limit orders for a symbol
- `_apply_slippage(price, side)` — adjust price by slippage bps
- `_apply_commission(fill_price, quantity)` — compute net fill value after commission
- `_next_order_id()` — generate unique order ID

### Data Structures
- `_prices: dict[str, float]` — last known price per symbol
- `_pending_orders: dict[str, PendingOrder]` — limit orders waiting for fill
- `_filled_orders: dict[str, FilledOrder]` — completed orders
- `_order_counter: int` — monotonic counter for order IDs

### File Layout
- Implementation: `src/trading_platform/replay/simulated_broker.py`
- Tests: `tests/test_simulated_broker.py`
