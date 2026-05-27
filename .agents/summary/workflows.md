# Workflows

## 1. Signal-to-Fill Pipeline (Core Trading Flow)

```mermaid
sequenceDiagram
    participant S as Strategy
    participant EB as EventBus
    participant RE as RiskEngine
    participant EE as ExecutionEngine
    participant BR as Broker/SimBroker
    participant PM as PositionManager
    participant ME as MetricsEngine

    Note over S,ME: 1. Signal Generation
    S->>EB: publish(SignalGeneratedEvent)
    EB->>RE: dispatch

    Note over RE: 2. Risk Checks
    RE->>RE: check_max_position_size
    RE->>RE: check_daily_loss
    RE->>RE: check_leverage
    RE->>RE: check_symbol_exposure
    RE->>RE: check_concurrent_positions
    RE->>RE: check_stale_market

    alt All checks pass
        RE->>EB: publish(SignalApprovedEvent)
        EB->>EE: dispatch

        Note over EE: 3. Sizing & Throttle
        EE->>EE: check throttle per symbol
        EE->>EE: compute final size via SizingEngine

        alt Throttled
            EE->>EB: publish(OrderSubmittedEvent with quantity=0)
        else Passes throttle
            EE->>EB: publish(OrderRequestedEvent)
            EB->>BR: dispatch
        end

        Note over BR: 4. Order Execution
        alt Live
            BR->>BR: IBKR API placeOrder()
        else Backtest
            BR->>BR: Check price, apply slippage/commission
        end
        BR->>EB: publish(OrderSubmittedEvent)
        BR->>EB: publish(OrderFilledEvent)

        EB->>PM: dispatch

        Note over PM: 5. Position Tracking
        PM->>PM: update avg cost, realized PnL
        PM->>EB: publish(PositionOpenedEvent or PositionClosedEvent)
        PM->>EB: publish(PnLUpdatedEvent)
        PM->>EB: publish(ExposureUpdatedEvent)
        EB->>RE: dispatch (exposure auto-update)
        EB->>ME: dispatch

        Note over ME: 6. Metrics Tracking
        ME->>ME: record equity point
        ME->>ME: track fill value for turnover
        ME->>ME: count win/loss on close

    else Rejected
        RE->>EB: publish(SignalRejectedEvent)
        RE->>EB: publish(RiskViolationEvent)
        EB->>ME: dispatch (AlertManager)
    end
```

## 2. Connection Lifecycle & Reconnection

```mermaid
stateDiagram-v2
    [*] --> Disconnected
    Disconnected --> Connecting: connect()
    Connecting --> Connected: successful
    Connecting --> Disconnected: failed
    Connected --> Disconnected: disconnect()
    Connected --> Disconnected: connection lost
    Disconnected --> Reconnecting: auto (if running)
    Reconnecting --> Connected: successful
    Reconnecting --> Failed: max attempts exceeded
    Failed --> [*]

    state Reconnecting {
        [*] --> Wait: sleep interval
        Wait --> Try: wake
        Try --> Success: connected
        Try --> Wait: failed, increment
    }
```

1. `IBKRClient.connect()` opens IBKR Gateway connection
2. Publishes `BrokerReconnectedEvent` on success
3. Sets up `disconnectedEvent` handler and starts heartbeat loop
4. On disconnect, publishes `BrokerDisconnectedEvent` → triggers kill switch in `RiskEngine`
5. Reconnect loop retries with configurable interval and max attempts
6. On reconnect success, publishes `BrokerReconnectedEvent` → triggers `MarketDataFeed` re-subscription
7. `AlertManager` monitors disconnect/reconnect events and heartbeat health

## 3. Market Data Flow (Live)

```mermaid
sequenceDiagram
    participant IB as IBKR Gateway
    participant MDF as MarketDataFeed
    participant EB as EventBus
    participant BA as BarAggregator
    participant Sub as Subscribers

    IB->>MDF: pendingTickers
    MDF->>MDF: _process_tickers()
    MDF->>IB: ticker.contract.symbol
    MDF->>MDF: _ticker_to_event()

    alt Has price data
        MDF->>EB: publish(MarketTickEvent)
    end

    MDF->>BA: add_tick()

    alt Time window elapsed
        BA-->>MDF: BarCloseEvent
        MDF->>EB: publish(BarCloseEvent)
    else Window not elapsed
        BA-->>MDF: None
    end

    EB->>Sub: dispatch to subscribers
```

- Tick-triggered bar aggregation: bar emitted when new tick arrives AFTER the time window has elapsed
- Price data is the primary source; bid/ask used as fallback when last price is 0

## 4. Position Management Flow

```mermaid
stateDiagram-v2
    state "No Position" as NP
    state "Long Position" as LP
    state "Short Position" as SP

    [*] --> NP
    NP --> LP: BUY fill (quantity > 0)
    NP --> SP: SELL fill (quantity < 0)
    LP --> LP: Additional BUY (avg cost updated)
    LP --> NP: SELL fill (covers all)
    LP --> SP: SELL fill (oversells)
    SP --> SP: Additional SELL (avg cost updated)
    SP --> NP: BUY fill (covers all)
    SP --> LP: BUY fill (overbuys)
```

### Position Update Rules
- **BUY when long/neutral:** Increases quantity, recalculates avg cost (weighted average)
- **SELL when short/neutral:** Increases short quantity, recalculates avg cost
- **BUY when short (covering):** Realizes PnL on covered shares, may flip to long
- **SELL when long (reducing):** Realizes PnL on reduced shares, may flip to short

## 5. Order Execution (Simulated)

```mermaid
flowchart TD
    ORE[OrderRequestedEvent] --> Type{Order Type}
    Type -->|MKT| HasPrice{Price available?}
    HasPrice -->|Yes| FillMarket[Fill immediately at price + slippage]
    HasPrice -->|No| Hold[Held pending price arrival]

    Type -->|LMT| HasPrice2{Price available?}
    HasPrice2 -->|Yes| CheckLimit{Limit crossed?}
    HasPrice2 -->|No| Pend[Pending price arrival]
    CheckLimit -->|Yes| FillLMT[Fill at limit price]
    CheckLimit -->|No| Pend

    Hold --> Tick{New price arrives}
    Pend --> Tick
    Tick --> FillMarket
    Tick --> FillLMT

    FillMarket --> PubFill[Publish OrderSubmitted + OrderFilled]
    FillLMT --> PubFill
```

## 6. Backtest Metrics Computation

```mermaid
flowchart LR
    EUE[ExposureUpdatedEvent] --> EQ[Record equity curve point]
    OFE[OrderFilledEvent] --> TV[Accumulate traded value]
    PCE[PositionClosedEvent] --> WL[Count win/loss]
    EQ --> Compute
    TV --> Compute
    WL --> Compute
    Compute --> Result[BacktestMetrics]
    Result --> Ret[total_return]
    Result --> SR[sharpe_ratio]
    Result --> DD[max_drawdown]
    Result --> WR[win_rate]
    Result --> TO[turnover]
```

Metrics are computed lazily via `MetricsEngine.compute()`:
1. **Total Return**: `(end_eq - start_eq) / start_eq`
2. **Annualized Return**: `(1 + total_return)^(1/years) - 1`
3. **Sharpe Ratio**: Annualized excess return / annualized std dev of simple returns
4. **Max Drawdown**: Maximum peak-to-trough decline as percentage
5. **Win Rate**: Winning trades / total trades (zero PnL not counted)
6. **Turnover**: Total traded value / average equity

## 7. Risk Engine Checks

```mermaid
flowchart TD
    SGE[SignalGeneratedEvent] --> KS{Kill switch active?}
    KS -->|Yes| Reject[SignalRejectedEvent]
    KS -->|No| Checks

    Checks --> Size{Max position size}
    Size -->|Exceeds| RejectSize[Reject: size violation]
    Size -->|OK| Loss{Daily loss limit}
    Loss -->|Exceeded & not reducing| RejectLoss[Reject: daily loss]
    Loss -->|OK or reducing| Lev{Max leverage}
    Lev -->|Exceeded| RejectLev[Reject: leverage]
    Lev -->|OK| Exp{Max symbol exposure}
    Exp -->|Exceeded| RejectExp[Reject: exposure]
    Exp -->|OK| Conc{Max concurrent}
    Conc -->|Reached & new symbol| RejectConc[Reject: concurrent]
    Conc -->|OK| Stale{Stale market data}
    Stale -->|Stale| RejectStale[Reject: stale market]
    Stale -->|Fresh| Approve[SignalApprovedEvent]
```

## 8. Development Mode Data Flow (ReplayEngine)

```mermaid
sequenceDiagram
    participant CSV as data/*.csv
    participant HF as HistoricalFeed
    participant RE as ReplayEngine
    participant EB as EventBus
    participant S as Strategy
    participant Rest as Pipeline Components

    Note over CSV,Rest: Application.startup() for development environment

    HF->>CSV: load_csv(path, symbol)
    HF->>HF: parse rows → BarCloseEvent list
    HF->>RE: load_events(events)
    RE->>RE: sort by timestamp

    Note over RE: launched as asyncio.create_task(replay.run())

    loop For each Event
        RE->>RE: set clock time
        RE->>EB: publish(BarCloseEvent)
        EB->>S: dispatch
        S->>S: on_event() → check signal
        alt Signal triggered
            S->>EB: publish(SignalGeneratedEvent)
            EB->>Rest: dispatch (risk→exec→broker→position)
        end
        RE->>RE: sleep(delta / speed)
    end

    Note over RE: replay completes → task exits
```

- Only runs in `development` environment (skipped for `paper`/`live`)
- Reads CSV files from `data/` directory (filename = symbol, e.g. `AAPL.csv`)
- `HistoricalFeed` handles column mapping, date filtering, and malformed row skipping
- `ReplayEngine` publishes events at clock-adjusted cadence (real-time at speed=1)
- Same downstream pipeline processes events regardless of source (live or replay)

## 9. Monitoring Alert Flow

```mermaid
flowchart TD
    BDE[BrokerDisconnectedEvent] --> Alert[AlertManager]
    BRE[BrokerReconnectedEvent] --> Alert
    RVE[RiskViolationEvent] --> Alert
    SRE[SignalRejectedEvent] --> Alert
    THE[TradingHaltedEvent] --> Alert
    HE[HeartbeatEvent] --> Alert

    Alert --> Check{Cooldown check}
    Check -->|Within cooldown| Skip[Suppress duplicate]
    Check -->|Cooldown expired| Pub[Publish AlertEvent]

    HE --> Reset[Reset last_heartbeat]
    Alert --> CheckHB{Heartbeat timeout?}
    CheckHB -->|Missed| Pub
```

- Cooldown per `alert_type` string key (e.g., `broker_disconnected`, `risk_violation_*`)
- Heartbeat check runs at `heartbeat_timeout / 2` frequency
- If no heartbeat within timeout, publishes `AlertEvent` with severity `ERROR`
