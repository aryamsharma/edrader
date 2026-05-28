from __future__ import annotations

import asyncio

import pytest

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BaseEvent,
    EventPriority,
    HeartbeatEvent,
    MarketTickEvent,
)


@pytest.mark.asyncio
async def test_publish_and_receive() -> None:
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.subscribe(MarketTickEvent, handler)
    await bus.start()

    event = MarketTickEvent(symbol="AAPL", price=150.0)
    await bus.publish(event)
    await bus._queue.join()

    await bus.stop()
    assert len(received) == 1
    assert received[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_multiple_subscribers() -> None:
    bus = EventBus()
    received_1: list[BaseEvent] = []
    received_2: list[BaseEvent] = []

    async def handler_1(event: BaseEvent) -> None:
        received_1.append(event)

    async def handler_2(event: BaseEvent) -> None:
        received_2.append(event)

    bus.subscribe(HeartbeatEvent, handler_1)
    bus.subscribe(HeartbeatEvent, handler_2)
    await bus.start()

    event = HeartbeatEvent()
    await bus.publish(event)
    await bus._queue.join()

    await bus.stop()
    assert len(received_1) == 1
    assert len(received_2) == 1


@pytest.mark.asyncio
async def test_subscriber_isolation() -> None:
    bus = EventBus()
    received_market: list[BaseEvent] = []
    received_heartbeat: list[BaseEvent] = []

    async def market_handler(event: BaseEvent) -> None:
        received_market.append(event)

    async def heartbeat_handler(event: BaseEvent) -> None:
        received_heartbeat.append(event)

    bus.subscribe(MarketTickEvent, market_handler)
    bus.subscribe(HeartbeatEvent, heartbeat_handler)
    await bus.start()

    await bus.publish(MarketTickEvent(symbol="AAPL", price=150.0))
    await bus.publish(HeartbeatEvent())
    await bus._queue.join()

    await bus.stop()
    assert len(received_market) == 1
    assert len(received_heartbeat) == 1


@pytest.mark.asyncio
async def test_unsubscribe() -> None:
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.subscribe(HeartbeatEvent, handler)
    bus.unsubscribe(HeartbeatEvent, handler)
    await bus.start()

    await bus.publish(HeartbeatEvent())
    await bus._queue.join()

    await bus.stop()
    assert len(received) == 0


@pytest.mark.asyncio
async def test_fifo_ordering() -> None:
    bus = EventBus()
    received: list[str] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event.event_id)

    class TestEvent(BaseEvent):
        pass

    bus.subscribe(TestEvent, handler)
    await bus.start()

    e1 = TestEvent()
    e2 = TestEvent()
    e3 = TestEvent()
    await bus.publish(e1)
    await bus.publish(e2)
    await bus.publish(e3)
    await bus._queue.join()

    await bus.stop()
    assert received == [e1.event_id, e2.event_id, e3.event_id]


@pytest.mark.asyncio
async def test_handler_exception_does_not_crash_bus() -> None:
    bus = EventBus()

    async def failing_handler(event: BaseEvent) -> None:  # noqa: ARG001
        raise ValueError("handler failed")

    async def good_handler(event: BaseEvent) -> None:  # noqa: ARG001
        pass

    bus.subscribe(HeartbeatEvent, failing_handler)
    bus.subscribe(HeartbeatEvent, good_handler)
    await bus.start()

    await bus.publish(HeartbeatEvent())
    await bus._queue.join()

    await bus.stop()


@pytest.mark.asyncio
async def test_queue_size_tracking() -> None:
    bus = EventBus(max_queue_size=5)
    await bus.start()
    assert bus.queue_size == 0

    for _ in range(3):
        await bus.publish(HeartbeatEvent())
    assert bus.queue_size == 3

    await bus._queue.join()
    assert bus.queue_size == 0
    await bus.stop()


@pytest.mark.asyncio
async def test_start_stop_idempotent() -> None:
    bus = EventBus()
    await bus.start()
    await bus.start()
    await bus.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_wildcard_subscriber() -> None:
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.subscribe_all(handler)
    await bus.start()

    await bus.publish(MarketTickEvent(symbol="AAPL", price=150.0))
    await bus.publish(HeartbeatEvent())
    await bus._queue.join()

    await bus.stop()
    assert len(received) == 2


@pytest.mark.asyncio
async def test_event_filter() -> None:
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.subscribe(
        MarketTickEvent,
        handler,
        event_filter=lambda e: isinstance(e, MarketTickEvent) and e.symbol == "AAPL",
    )
    await bus.start()

    await bus.publish(MarketTickEvent(symbol="AAPL", price=150.0))
    await bus.publish(MarketTickEvent(symbol="GOOG", price=2800.0))
    await bus._queue.join()

    await bus.stop()
    assert len(received) == 1
    assert received[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_priority_queue_ordering() -> None:
    bus = EventBus()
    received: list[str] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event.event_id)

    class TestEvent(BaseEvent):
        pass

    bus.subscribe(TestEvent, handler)
    await bus.start()

    normal = TestEvent(priority=EventPriority.NORMAL)
    critical = TestEvent(priority=EventPriority.CRITICAL)
    low = TestEvent(priority=EventPriority.LOW)
    high = TestEvent(priority=EventPriority.HIGH)

    await bus.publish(normal)
    await bus.publish(critical)
    await bus.publish(low)
    await bus.publish(high)
    await bus._queue.join()

    await bus.stop()
    assert received[0] == critical.event_id
    assert received[1] == high.event_id


@pytest.mark.asyncio
async def test_error_handler_called() -> None:
    errors: list[tuple[BaseEvent, Exception]] = []

    def error_handler(event: BaseEvent, exc: Exception) -> None:
        errors.append((event, exc))

    bus = EventBus(error_handler=error_handler)

    async def failing_handler(event: BaseEvent) -> None:  # noqa: ARG001
        raise RuntimeError("boom")

    bus.subscribe(HeartbeatEvent, failing_handler)
    await bus.start()

    event = HeartbeatEvent()
    await bus.publish(event)
    await bus._queue.join()

    await bus.stop()
    assert len(errors) == 1
    assert errors[0][0].event_id == event.event_id
    assert isinstance(errors[0][1], RuntimeError)


@pytest.mark.asyncio
async def test_metrics_snapshot() -> None:
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.subscribe(MarketTickEvent, handler)
    bus.subscribe(HeartbeatEvent, handler)
    await bus.start()

    await bus.publish(MarketTickEvent(symbol="AAPL", price=150.0))
    await bus.publish(HeartbeatEvent())
    await bus._queue.join()

    await bus.stop()
    snap = bus.metrics.snapshot()
    assert snap["total_published"] == 2
    assert snap["total_dispatched"] == 2
    assert snap["total_errors"] == 0
    assert "MarketTickEvent" in snap["events_by_type"]
    assert "HeartbeatEvent" in snap["events_by_type"]


@pytest.mark.asyncio
async def test_subscriber_count() -> None:
    bus = EventBus()

    async def h1(event: BaseEvent) -> None:
        pass

    async def h2(event: BaseEvent) -> None:
        pass

    bus.subscribe(MarketTickEvent, h1)
    bus.subscribe(HeartbeatEvent, h2)
    bus.subscribe_all(h1)

    assert bus.subscriber_count == 3
    assert bus.subscriber_count_for(MarketTickEvent) == 1
    assert bus.subscriber_count_for(HeartbeatEvent) == 1


@pytest.mark.asyncio
async def test_slow_handler_timeout() -> None:
    bus = EventBus(subscriber_timeout=0.01)
    received: list[BaseEvent] = []

    async def slow_handler(event: BaseEvent) -> None:  # noqa: ARG001
        await asyncio.sleep(10)

    async def fast_handler(event: BaseEvent) -> None:
        received.append(event)

    bus.subscribe(HeartbeatEvent, slow_handler, name="slow")
    bus.subscribe(HeartbeatEvent, fast_handler, name="fast")
    await bus.start()

    event = HeartbeatEvent()
    await bus.publish(event)
    await bus._queue.join()

    await bus.stop()
    assert len(received) == 1  # fast handler still ran
    assert bus.metrics.total_errors >= 1
    assert bus.metrics.errors_by_type["HeartbeatEvent"] >= 1


@pytest.mark.asyncio
async def test_slow_handler_does_not_block_other_events() -> None:
    bus = EventBus(subscriber_timeout=0.01)
    fast_events: list[BaseEvent] = []

    async def slow_handler(event: BaseEvent) -> None:  # noqa: ARG001
        await asyncio.sleep(10)

    async def fast_handler(event: BaseEvent) -> None:
        fast_events.append(event)

    bus.subscribe(HeartbeatEvent, slow_handler, name="slow")
    bus.subscribe(HeartbeatEvent, fast_handler, name="fast")
    await bus.start()

    await bus.publish(HeartbeatEvent())
    await bus._queue.join()

    assert len(fast_events) == 1

    await bus.publish(HeartbeatEvent())
    await bus._queue.join()

    assert len(fast_events) == 2  # bus still processes after timeout
    await bus.stop()
