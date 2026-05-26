# Market Data Feed — Plan

## Test Strategy

### Test Classes
- `TestMarketDataFeedSubscribe` — subscription management
- `TestMarketDataFeedTickHandling` — tick receipt and event emission
- `TestMarketDataFeedBarAggregation` — bar aggregation from ticks
- `TestMarketDataFeedLifecycle` — start/stop/reconnect behavior

### Test Scenarios
1. Initial state: not running, no subscriptions
2. `subscribe_symbol()` adds symbol to subscription list
3. `subscribe_symbol()` sets up ib_insync market data request
4. Tick handler emits `MarketTickEvent` for price/volume updates
5. Tick handler emits `MarketTickEvent` for bid/ask updates
6. `unsubscribe()` removes symbol and cancels market data
7. `stop()` clears subscriptions and cleans up handlers
8. Re-subscription on `BrokerReconnectedEvent`
9. Bar aggregation: ticks within window produce `BarCloseEvent`
10. Bar aggregation: no event until enough time passes
11. Multiple symbols tracked independently
12. Error handling: bad tick data doesn't crash the feed

## Implementation Plan
1. **`BarAggregator`** — time-windowed OHLCV aggregation from `MarketTickEvent` → `BarCloseEvent`
2. **`MarketDataFeed`** — orchestrate subscriptions, tick handling, event publishing
   - Constructor: `(ib, event_bus, default_bar_size_seconds=60)`
   - `start()` / `stop()` — lifecycle
   - `subscribe_symbol(symbol, exchange, currency, bar_size)` — single symbol
   - `subscribe_symbols(symbols, ...)` — batch
   - `unsubscribe(symbol)` — remove
   - `unsubscribe_all()` — clear all
   - `subscriptions` — property returning active symbols
   - Handles `BrokerReconnectedEvent` for auto re-subscribe
3. Tick normalization inline (simple mapping from ib_insync Ticker fields)
