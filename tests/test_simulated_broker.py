from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BarCloseEvent,
    MarketTickEvent,
    OrderFilledEvent,
    OrderRequestedEvent,
    OrderStatusChangedEvent,
    OrderSubmittedEvent,
)
from trading_platform.replay.simulated_broker import SimulatedBroker


@pytest.fixture
async def event_bus() -> EventBus:
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
def collected_events(event_bus: EventBus) -> list:
    events: list = []

    async def collector(event: object) -> None:
        events.append(event)

    event_bus.subscribe_all(collector, name="collector")
    return events


@pytest.fixture
async def broker(event_bus: EventBus) -> SimulatedBroker:
    b = SimulatedBroker(event_bus=event_bus)
    await b.start()
    yield b
    await b.stop()


def _ts(offset_seconds: int = 0) -> datetime:
    return datetime(2024, 1, 1, 9, 30, tzinfo=UTC) + timedelta(seconds=offset_seconds)


class TestSimulatedBrokerLifecycle:
    async def test_initial_state(self, event_bus: EventBus) -> None:
        b = SimulatedBroker(event_bus=event_bus)
        assert b.is_running is False
        assert b.active_order_ids == []

    async def test_start_sets_running(self, event_bus: EventBus) -> None:
        b = SimulatedBroker(event_bus=event_bus)
        await b.start()
        assert b.is_running is True
        await b.stop()

    async def test_stop_clears_running(self, broker: SimulatedBroker) -> None:
        await broker.stop()
        assert broker.is_running is False

    async def test_start_idempotent(self, broker: SimulatedBroker) -> None:
        await broker.start()
        assert broker.is_running is True

    async def test_stop_idempotent(self, broker: SimulatedBroker) -> None:
        await broker.stop()
        await broker.stop()
        assert broker.is_running is False

    async def test_subscribes_to_order_requests(
        self, broker: SimulatedBroker, event_bus: EventBus
    ) -> None:
        assert broker.is_running
        assert event_bus.subscriber_count_for(OrderRequestedEvent) >= 1

    async def test_subscribes_to_bar_close(
        self, broker: SimulatedBroker, event_bus: EventBus
    ) -> None:
        assert broker.is_running
        assert event_bus.subscriber_count_for(BarCloseEvent) >= 1

    async def test_subscribes_to_market_ticks(
        self, broker: SimulatedBroker, event_bus: EventBus
    ) -> None:
        assert broker.is_running
        assert event_bus.subscriber_count_for(MarketTickEvent) >= 1

    async def test_stop_clears_prices_and_orders(self, broker: SimulatedBroker) -> None:
        await broker.stop()
        assert broker.active_order_ids == []


@pytest.mark.usefixtures("broker")
class TestSimulatedBrokerMarketOrder:
    async def test_market_order_buy_fills_at_price(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        submitted = [e for e in collected_events if isinstance(e, OrderSubmittedEvent)]
        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(submitted) >= 1
        assert len(filled) >= 1
        assert filled[0].symbol == "AAPL"
        assert filled[0].side == "BUY"
        assert filled[0].fill_quantity == 100
        assert filled[0].fill_price == 150.0

    async def test_market_order_sell_fills_at_price(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="SELL",
                quantity=50,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].side == "SELL"
        assert filled[0].fill_quantity == 50
        assert filled[0].fill_price == 150.0

    async def test_submitted_event_before_filled(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        submitted_events = [e for e in collected_events if isinstance(e, OrderSubmittedEvent)]
        filled_events = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        submitted_idx = collected_events.index(submitted_events[0])
        filled_idx = collected_events.index(filled_events[0])
        assert submitted_idx < filled_idx

    async def test_market_order_without_price_held(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="UNKNOWN",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) == 0

    async def test_market_order_fills_when_price_arrives(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=155.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 155.0

    async def test_market_order_before_start_ignored(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        SimulatedBroker(event_bus=event_bus)

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) == 0


@pytest.mark.usefixtures("broker")
class TestSimulatedBrokerSubmittedEvent:
    async def test_submitted_event_has_order_id(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        submitted = [e for e in collected_events if isinstance(e, OrderSubmittedEvent)]
        assert len(submitted) >= 1
        assert len(submitted[0].order_id) > 0


@pytest.mark.usefixtures("broker")
class TestSimulatedBrokerLimitOrder:
    async def test_limit_order_buy_fills_when_price_drops(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="LMT",
                limit_price=148.0,
                source="test",
            )
        )
        await event_bus.drain()

        filled_before = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled_before) == 0

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=147.5, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 148.0

    async def test_limit_order_sell_fills_when_price_rises(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="SELL",
                quantity=100,
                order_type="LMT",
                limit_price=152.0,
                source="test",
            )
        )
        await event_bus.drain()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=152.5, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 152.0

    async def test_limit_order_does_not_fill_before_cross(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="LMT",
                limit_price=148.0,
                source="test",
            )
        )
        await event_bus.drain()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) == 0

    async def test_limit_order_fills_at_exact_limit(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="LMT",
                limit_price=150.0,
                source="test",
            )
        )
        await event_bus.drain()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1

    async def test_multiple_limit_orders_fill_on_price(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=50,
                order_type="LMT",
                limit_price=148.0,
                source="test",
            )
        )
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=30,
                order_type="LMT",
                limit_price=148.0,
                source="test",
            )
        )
        await event_bus.drain()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=147.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) == 2


class TestSimulatedBrokerCommissions:
    async def test_commission_deducted_from_fill_value(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        b = SimulatedBroker(event_bus=event_bus, commission_per_trade=1.50)
        await b.start()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=100.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=10,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 100.0
        assert filled[0].fill_quantity == 10

        total_events = [e for e in collected_events if isinstance(e, OrderSubmittedEvent)]
        assert len(total_events) >= 1
        await b.stop()

    async def test_zero_commission_no_deduction(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        b = SimulatedBroker(event_bus=event_bus, commission_per_trade=0.0)
        await b.start()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=100.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=10,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        await b.stop()


class TestSimulatedBrokerSlippage:
    async def test_slippage_applied_to_buy(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        b = SimulatedBroker(event_bus=event_bus, slippage_bps=10.0)
        await b.start()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=100.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 100.10
        await b.stop()

    async def test_slippage_applied_to_sell(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        b = SimulatedBroker(event_bus=event_bus, slippage_bps=10.0)
        await b.start()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=100.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="SELL",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 99.90
        await b.stop()

    async def test_zero_slippage_exact_price(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        b = SimulatedBroker(event_bus=event_bus, slippage_bps=0.0)
        await b.start()

        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=100.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 100.0
        await b.stop()


@pytest.mark.usefixtures("broker")
class TestSimulatedBrokerPriceSource:
    async def test_bar_close_provides_price(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=200.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=50,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 200.0

    async def test_tick_provides_price(self, collected_events: list, event_bus: EventBus) -> None:
        await event_bus.publish(
            MarketTickEvent(symbol="AAPL", price=175.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=50,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 175.0

    async def test_tick_price_overrides_bar_close(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=200.0, timestamp=_ts(), source="test")
        )
        await event_bus.publish(
            MarketTickEvent(symbol="AAPL", price=180.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=50,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].fill_price == 180.0


@pytest.mark.usefixtures("broker")
class TestSimulatedBrokerOrderTracking:
    async def test_multiple_symbols_tracked_independently(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.publish(
            BarCloseEvent(symbol="MSFT", close=300.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="MSFT",
                side="SELL",
                quantity=50,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) == 2

        aapl_fills = [f for f in filled if f.symbol == "AAPL"]
        msft_fills = [f for f in filled if f.symbol == "MSFT"]
        assert len(aapl_fills) == 1
        assert aapl_fills[0].fill_price == 150.0
        assert len(msft_fills) == 1
        assert msft_fills[0].fill_price == 300.0

    async def test_active_order_ids_tracked(
        self, broker: SimulatedBroker, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="SELL",
                quantity=100,
                order_type="LMT",
                limit_price=200.0,
                source="test",
            )
        )
        await event_bus.drain()

        assert len(broker.active_order_ids) >= 1

    async def test_submitted_event_has_source(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        submitted = [e for e in collected_events if isinstance(e, OrderSubmittedEvent)]
        assert len(submitted) >= 1
        assert submitted[0].source == "simulated_broker"

    async def test_filled_event_has_source(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        filled = [e for e in collected_events if isinstance(e, OrderFilledEvent)]
        assert len(filled) >= 1
        assert filled[0].source == "simulated_broker"


@pytest.mark.usefixtures("broker")
class TestSimulatedBrokerStatusEvents:
    async def test_status_changed_event_emitted(
        self, collected_events: list, event_bus: EventBus
    ) -> None:
        await event_bus.publish(
            BarCloseEvent(symbol="AAPL", close=150.0, timestamp=_ts(), source="test")
        )
        await event_bus.drain()

        await event_bus.publish(
            OrderRequestedEvent(
                symbol="AAPL",
                side="BUY",
                quantity=100,
                order_type="MKT",
                source="test",
            )
        )
        await event_bus.drain()

        status = [e for e in collected_events if isinstance(e, OrderStatusChangedEvent)]
        assert len(status) >= 1
