# Architecture

## Overview
The trading platform is an **event-driven modular monolith** — a single process with a single asyncio event loop where all communication between modules flows through typed domain events on a central `EventBus`.

```mermaid
graph TB
    subgraph Sources
        STR[Strategies]
        IB[IBKR / Gateway]
        HF[Historical Feed]
    end

    subgraph Core
        EB[EventBus]
        EJ[EventJournal]
    end

    subgraph Processing
        RE[RiskEngine]
        EE[ExecutionEngine]
        PM[PositionManager]
        ME[MetricsEngine]
        AG[AlertManager]
    end

    subgraph Execution
        SA[SimulatedBroker]
        BA[BrokerAdapter]
        MDF[MarketDataFeed]
    end

    STR -->|SignalGeneratedEvent| EB
    IB -->|MarketTickEvent| EB
    HF -->|BarCloseEvent| EB
    EB --> RE
    RE -->|SignalApprovedEvent| EB
    EB --> EE
    EE -->|OrderRequestedEvent| EB
    EB --> SA
    EB --> BA
    SA -->|OrderFilledEvent| EB
    BA -->|OrderFilledEvent| EB
    EB --> PM
    PM -->|ExposureUpdatedEvent| EB
    EB --> ME
    EB --> AG
    EB -.->|logs all| EJ
```

## Key Design Decisions

### Event-Driven Architecture
- `EventBus` is the central nervous system — a typed async pub/sub with dual priority queues (HIGH/CRITICAL vs NORMAL/LOW)
- All components subscribe to specific event types and publish events
- No direct method calls between business modules (except `broker/` internals)
- EventJournal provides SQLite append-only persistence for replay/audit

### Component Lifecycle
Every component follows a consistent lifecycle pattern:
```mermaid
stateDiagram-v2
    [*] --> Stopped
    Stopped --> Running: start()
    Running --> Stopped: stop()
    Running --> Running: start() [idempotent, no-op]
    Stopped --> Stopped: stop() [idempotent, no-op]
```

Each component:
- Has a boolean `is_running` property
- Subscribes to events on `start()` and returns unsubscribe callables
- Unsubscribes on `stop()`
- Ignores events received when `_running` is False

### Event Bus Architecture
```mermaid
graph LR
    subgraph Publishers
        A[Strategy]
        B[MarketData]
        C[IBKRClient]
    end
    A -->|put| PQ[PriorityQueue]
    B -->|put| PQ
    C -->|put| PQ
    PQ -->|get| DP[Dispatch Loop]
    DP -->|dispatch| S1[Subscriber 1]
    DP -->|dispatch| S2[Subscriber 2]
    DP -->|dispatch| S3[Subscriber 3]
```

- `PriorityQueue` wraps two `asyncio.Queue` instances (high/normal)
- Dispatch loop runs in a single `asyncio.Task`, draining events sequentially
- Errors in handlers don't crash the bus — they're logged and optionally passed to an error handler
- `drain()` awaits both queues to be empty (for test synchronization)

### IBKR Isolation Boundary
- `ib_insync` types (`IB`, `Contract`, `Ticker`, `Trade`) are typed as `Any` and never appear outside `broker/`
- All cross-module communication uses domain events defined in `events/event_types.py`
- The `broker/` module has three components:
  - `IBKRClient` — connection lifecycle, heartbeat, reconnection
  - `MarketDataFeed` — tick subscriptions, bar aggregation
  - `BrokerAdapter` — order placement, status tracking, fill handling

### Live vs Backtest Parity
- Same code path executes both live and in backtest
- Live: `IBKRClient` + `MarketDataFeed` + `BrokerAdapter` (real IBKR)
- Backtest: `ReplayClock` + `HistoricalFeed` + `SimulatedBroker` (simulated)
- All downstream components (`RiskEngine`, `ExecutionEngine`, `PositionManager`, etc.) remain identical

```mermaid
graph TB
    subgraph Live
        IB[IBKR Gateway]
        MDF[MarketDataFeed]
        BA[BrokerAdapter]
    end
    subgraph Backtest
        RC[ReplayClock]
        HF[HistoricalFeed]
        SB[SimulatedBroker]
    end
    subgraph Shared
        EB[EventBus]
        RE[RiskEngine]
        EE[ExecutionEngine]
        PM[PositionManager]
    end
    Live --> EB
    Backtest --> EB
    EB --> Shared
```

## Module Dependency Graph
```mermaid
graph TD
    app --> events
    app --> monitoring
    broker --> events
    broker --> app
    events --> monitoring
    execution --> events
    monitoring --> events
    persistence --> events
    portfolio --> events
    replay --> events
    risk --> events
    strategies --> events
```

Note: All modules depend on `events/` (for event types and bus) and `monitoring/` (for logging). The `app/` module wires everything together at startup.
