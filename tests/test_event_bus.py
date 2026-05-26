from __future__ import annotations

import pytest

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BaseEvent,
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

    async def good_handler(event: BaseEvent) -> None:
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
