# Key Workflows

## Event Publication and Dispatch

```mermaid
sequenceDiagram
    participant Pub as Publisher
    participant Bus as EventBus
    participant PQ as PriorityQueue
    participant Disp as Dispatcher
    participant Sub as Subscriber

    Pub->>Bus: publish(event)
    Bus->>Bus: metrics.total_published++
    Bus->>PQ: await put(event)

    Note over Bus,Disp: background _process_events loop

    loop every 0.5s poll
        Disp->>PQ: await get() [polls high first]
        PQ-->>Disp: event or timeout
        alt event received
            Disp->>Disp: find matching subscribers
            Disp->>Sub: await handler(event)
            Disp->>Bus: metrics update
            Disp->>PQ: task_done()
        else timeout
            Disp->>Disp: continue loop
        end
    end
```

## IBKR Connection Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Disconnected
    Disconnected --> Connecting: connect()
    Connecting --> Connected: connectAsync success
    Connecting --> Disconnected: connectAsync failure
    Connected --> Disconnected: disconnect() / connection lost
    Disconnected --> Reconnecting: _on_disconnected_async (if running)
    Reconnecting --> Connected: reconnect success
    Reconnecting --> Disconnected: max attempts exceeded
    Connected --> Connected: heartbeat checks connection
```

## Market Data Flow

```mermaid
sequenceDiagram
    participant Feed as MarketDataFeed
    participant IB as ib_insync
    participant Bus as EventBus
    participant Agg as BarAggregator

    Feed->>IB: reqMktData(contract)
    IB-->>Feed: Ticker object

    loop pendingTickersEvent
        IB->>Feed: _on_pending_tickers()
        Feed->>Feed: _process_tickers(tickers)
        alt ticker symbol is subscribed
            Feed->>Feed: _ticker_to_event()
            Feed->>Bus: publish(MarketTickEvent)
            Feed->>Agg: add_tick(tick)
            alt bar window elapsed
                Agg-->>Feed: BarCloseEvent
                Feed->>Bus: publish(BarCloseEvent)
            end
        end
    end
```

## Reconnection and Re-subscription

```mermaid
sequenceDiagram
    participant IB as ib_insync
    participant Client as IBKRClient
    participant Bus as EventBus
    participant Feed as MarketDataFeed

    IB->>Client: disconnectedEvent fires
    Client->>Bus: publish(BrokerDisconnectedEvent)
    Client->>Client: start reconnect loop

    loop until connected or max attempts
        Client->>IB: connectAsync()
        alt success
            Client->>Bus: publish(BrokerReconnectedEvent)
            Bus->>Feed: on_reconnect handler
            Feed->>Feed: _re_subscribe_all()
            Feed->>IB: reqMktData for each symbol
        else failure
            Client->>Client: sleep + retry
        end
    end
```

## Test-Driven Development Cycle

```mermaid
graph LR
    R[RED: Write failing test] --> G[GREEN: Implement minimal code]
    G --> R2[REFACTOR: Clean up]
    R2 --> L[Lint: ruff check]
    L --> F[Format: ruff format]
    F --> T[TypeCheck: mypy]
    T --> P[Test: pytest]
    P --> C[Commit]
```

## Commit Conventions

| Pattern | Example |
|---|---|
| `Phase X.Y: description` | `Phase 2.2: market data feed with tick subscriptions and bar aggregation` |
| `docs: description` | `docs: add AGENTS.md with commands, architecture, conventions` |

Full workflow: `ruff check && ruff format . && mypy src/ && pytest`
