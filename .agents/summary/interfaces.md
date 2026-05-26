# Interfaces and Integration Points

## EventBus Public API

```python
class EventBus:
    def subscribe(
        event_type: type[BaseEvent],
        handler: AsyncHandler,  # Callable[[BaseEvent], Awaitable[None]]
        event_filter: EventFilter | None = None,  # Callable[[BaseEvent], bool]
        name: str = "",
    ) -> None

    def subscribe_all(
        handler: AsyncHandler,
        event_filter: EventFilter | None = None,
        name: str = "",
    ) -> None

    def unsubscribe(
        event_type: type[BaseEvent],
        handler: AsyncHandler,
    ) -> None

    async def publish(event: BaseEvent) -> None
    async def start() -> None
    async def stop() -> None
    async def drain() -> None
```

## BaseEvent Serialization Interface

```python
class BaseEvent:
    def to_dict() -> dict[str, Any]
    @classmethod def from_dict(data: dict[str, Any]) -> BaseEvent
```

## EventJournal Interface

```python
class EventJournal:
    def append(event: BaseEvent) -> int  # returns sequence number
    def replay(
        event_types: list[type[BaseEvent]] | None = None,
        since_sequence: int = 0,
        limit: int | None = None,
    ) -> list[BaseEvent]
    def count() -> int
    @property def last_sequence() -> int
    def close() -> None
```

## IBKRClient Interface

```python
class IBKRClient:
    def __init__(
        config: BrokerConfig,
        event_bus: EventBus,
        ib: Any = None,                    # Injectable mock for testing
        heartbeat_interval: float = 5.0,
    ) -> None

    async def connect() -> None
    async def disconnect() -> None
    @property def is_connected() -> bool
```

## MarketDataFeed Interface

```python
class MarketDataFeed:
    def __init__(
        ib: Any,
        event_bus: EventBus,
        default_bar_size_seconds: float = 60.0,
    ) -> None

    async def start() -> None
    async def stop() -> None
    async def subscribe_symbol(
        symbol: str,
        exchange: str = "SMART",
        currency: str = "USD",
        sec_type: str = "STK",
        bar_size_seconds: float | None = None,
    ) -> None
    async def subscribe_symbols(
        symbols: list[str],
        exchange: str = "SMART",
        currency: str = "USD",
        sec_type: str = "STK",
        bar_size_seconds: float | None = None,
    ) -> None
    async def unsubscribe(symbol: str) -> None
    async def unsubscribe_all() -> None
    @property def subscriptions() -> list[str]
    @property def is_running() -> bool
```

## Configuration Loading Interface

```python
# config.py
class TradingConfig(BaseModel): ...

def load_config(path: Path) -> TradingConfig
```

## Logging Interface

```python
# monitoring/logging.py
def setup_logging(log_level: str = "DEBUG") -> None
def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger
```

## ib_insync Wrapper Boundaries

The `ib_insync` library is used only within `broker/`:

| ib_insync API | Wrapped In | Notes |
|---|---|---|
| `IB()` | `ibkr_client.py` | Constructor, `# type: ignore[no-untyped-call]` |
| `ib.connectAsync()` | `ibkr_client.py` | Async connection |
| `ib.disconnect()` | `ibkr_client.py` | Sync disconnect |
| `ib.isConnected()` | `ibkr_client.py` | Connection check |
| `ib.pendingTickersEvent` | `market_data.py` | Tick subscription event |
| `ib.reqMktData()` | `market_data.py` | Market data request |
| `ib.cancelMktData()` | `market_data.py` | Cancel subscription |
| `Stock()` / `Contract()` | `market_data.py` | Contract creation |
| `ib.disconnectedEvent` | `ibkr_client.py` | Disconnect handler |

## Integration Points for Stub Modules

When implementing stub modules, they integrate via:

1. **EventBus subscription**: Subscribe to relevant event types
2. **EventBus publication**: Publish domain events for other modules
3. **Configuration**: Add config sections to `TradingConfig`
4. **Logging**: Call `get_logger(__name__)` for structured logging
