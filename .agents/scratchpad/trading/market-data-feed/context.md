# Market Data Feed — Context

## Project Structure
- Python 3.12+ trading platform using Poetry
- Event-driven modular monolith with asyncio
- 11 module dirs under `src/trading_platform/`; 6 are stubs
- Tests in `tests/` using pytest-asyncio (asyncio_mode=auto)
- Broker module at `src/trading_platform/broker/` — only IBKR types allowed here

## Existing Patterns
- `IBKRClient` in `broker/ibkr_client.py`: wraps ib_insync `IB`, takes `EventBus`, publishes events, mockable via constructor injection
- Tests use `MagicMock`/`AsyncMock` for ib_insync objects, `collected_events` fixture to capture events
- All events are `@dataclass(frozen=True, slots=True)` inheriting `BaseEvent`
- All handlers typed as `Callable[[BaseEvent], Awaitable[None]]`
- All public methods fully typed

## Requirements (Phase 2.2 — Market Data Feed)
1. **Live tick subscriptions** — subscribe/unsubscribe to market data by symbol
2. **Tick normalization** — convert ib_insync Ticker to `MarketTickEvent`
3. **Bar aggregation** — accumulate ticks into `BarCloseEvent` (configurable period)
4. **Subscription management** — track active subscriptions, re-subscribe after reconnect
5. **Lifecycle** — start/stop cleanly, handle disconnects

## Dependencies
- `ib_insync` (already in pyproject.toml)
- `EventBus` from `trading_platform.events.bus`
- `MarketTickEvent`, `BarCloseEvent` from `trading_platform.events.event_types`
- `BrokerReconnectedEvent` for re-subscription trigger

## File Layout
- Implementation: `src/trading_platform/broker/market_data.py`
- Tests: `tests/test_market_data.py`
