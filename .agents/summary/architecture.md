# System Architecture

## Architectural Style: Modular Monolith

The entire application runs in a single process, on a single machine, inside a single Python async event loop. Modules are logically separated but deployed together.

## Design Principles

- **Correctness over feature count** — deterministic behavior is paramount
- **Event-driven communication** — modules never directly manipulate each other's state
- **Immutable events** — all events are frozen dataclasses, the single source of truth
- **Broker encapsulation** — `ib_insync.IB` is private to `broker/`; domain events cross boundaries
- **Signal-only strategies** — strategies emit signals, never place orders or touch IBKR
- **Live/backtest parity** — same strategy code, same event flow; only data source and clock change

## Runtime Model

```mermaid
graph TB
    subgraph "Single Process — Single Event Loop"
        MC[main coroutine]
        EP[_process_events task]
        HL[heartbeat loop task]
        RL[reconnect loop task]
        TD[tick dispatch task]
    end

    MC --> EP
    MC --> HL
    MC --> RL
    MC --> TD
```

## Event Flow

```mermaid
sequenceDiagram
    participant P as Publisher
    participant EB as EventBus
    participant PQ as PriorityQueue
    participant DI as _dispatch
    participant S1 as Subscriber A
    participant S2 as Subscriber B
    participant EJ as EventJournal

    P->>EB: publish(event)
    EB->>PQ: put(event)
    PQ-->>EB: queued
    loop process_events
        PQ->>DI: get()
        DI->>S1: handler(event)
        DI->>S2: handler(event)
        DI->>EJ: append(event)
    end
```

## Priority Routing

```mermaid
graph LR
    P[Publisher] --> N[NORMAL/LOW queue]
    P --> H[HIGH/CRITICAL queue]
    H --> D[Dispatcher - polls high first]
    N --> D
    D --> S1[Subscribers]
    D --> S2[Wildcard subscribers]
```

## Module Architecture

```mermaid
graph TB
    subgraph "app"
        C[config.py]
        B[bootstrap.py]
        M[main.py]
    end

    subgraph "broker"
        I[ibkr_client.py]
        MD[market_data.py]
    end

    subgraph "events"
        ET[event_types.py]
        EB[bus.py]
        EJ[journal.py]
    end

    subgraph "monitoring"
        L[logging.py]
    end

    subgraph "stub modules"
        EX[execution/]
        PE[persistence/]
        PO[portfolio/]
        RE[replay/]
        RI[risk/]
        ST[strategies/]
    end

    I --> EB
    MD --> EB
    MD --> I
    B --> C
    B --> EB
    M --> B
    EB --> EJ
    L -.-> I
    L -.-> MD
    L -.-> EB
```

## Key Architectural Constraints

1. **IBKR types must NOT leak outside `broker/`** — `ib_insync.IB` is typed as `Any` in broker module, `IB()` constructor has `# type: ignore[no-untyped-call]`
2. **Strategies emit signals only** — they never place orders, call IBKR, or manage positions
3. **Same code path for live and backtest** — only the data source/clock changes
4. **All critical state transitions occur through events** — events are the single source of truth
5. **Modules communicate via EventBus** — no direct imports between domain modules
