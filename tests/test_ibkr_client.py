from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_platform.app.config import BrokerConfig
from trading_platform.broker.ibkr_client import IBKRClient
from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    BrokerDisconnectedEvent,
    BrokerReconnectedEvent,
    HeartbeatEvent,
)


@pytest.fixture
def broker_config() -> BrokerConfig:
    return BrokerConfig(
        host="127.0.0.1",
        port=4001,
        client_id=1,
        connect_timeout=5,
        reconnect_interval=0.05,
        max_reconnect_attempts=3,
    )


@pytest.fixture
def mock_ib() -> MagicMock:
    ib = MagicMock()
    ib.connectAsync = AsyncMock()
    ib.disconnect.return_value = None
    ib.isConnected.return_value = True
    ib.disconnectedEvent = MagicMock()
    ib.disconnectedEvent.connect.return_value = "handler_id"
    ib.disconnectedEvent.disconnect.return_value = None
    ib.connectedEvent = MagicMock()
    ib.connectedEvent.connect.return_value = "handler_id"
    return ib


@pytest.fixture
async def event_bus() -> EventBus:
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
async def client(
    broker_config: BrokerConfig,
    event_bus: EventBus,
    mock_ib: MagicMock,
) -> IBKRClient:
    cl = IBKRClient(
        config=broker_config,
        event_bus=event_bus,
        ib=mock_ib,
        heartbeat_interval=0.05,
    )
    yield cl
    if cl.is_connected:
        await cl.disconnect()


@pytest.fixture
def collected_events(event_bus: EventBus) -> list:
    events: list = []

    async def collector(event: object) -> None:
        events.append(event)

    event_bus.subscribe_all(collector, name="collector")
    return events


@pytest.fixture
async def connected_client(client: IBKRClient, event_bus: EventBus) -> IBKRClient:
    await client.connect()
    await event_bus.drain()
    return client


class TestIBKRClientConnect:
    async def test_connect_success(
        self, client: IBKRClient, mock_ib: MagicMock, event_bus: EventBus
    ) -> None:
        await client.connect()
        await event_bus.drain()

        mock_ib.connectAsync.assert_awaited_once_with(
            host="127.0.0.1",
            port=4001,
            clientId=1,
            timeout=5,
        )
        assert client.is_connected is True

    async def test_connect_emits_reconnected_event(
        self, client: IBKRClient, collected_events: list, event_bus: EventBus
    ) -> None:
        await client.connect()
        await event_bus.drain()

        reconnected = [e for e in collected_events if isinstance(e, BrokerReconnectedEvent)]
        assert len(reconnected) == 1
        assert reconnected[0].attempts == 0
        assert reconnected[0].source == "ibkr_client"

    async def test_connect_sets_up_disconnect_handler(
        self, client: IBKRClient, mock_ib: MagicMock
    ) -> None:
        await client.connect()
        mock_ib.disconnectedEvent.connect.assert_called_once()

    async def test_connect_starts_heartbeat(self, client: IBKRClient) -> None:
        await client.connect()
        assert client._heartbeat_task is not None
        assert not client._heartbeat_task.done()

    async def test_connect_propagation_failure(
        self, client: IBKRClient, mock_ib: MagicMock
    ) -> None:
        mock_ib.connectAsync.side_effect = ConnectionRefusedError("Connection refused")

        with pytest.raises(ConnectionRefusedError):
            await client.connect()
        assert client.is_connected is False

    async def test_connect_timeout(self, client: IBKRClient, mock_ib: MagicMock) -> None:
        mock_ib.connectAsync.side_effect = TimeoutError("Timeout")

        with pytest.raises(TimeoutError):
            await client.connect()
        assert client.is_connected is False

    async def test_connect_with_custom_ib(
        self, broker_config: BrokerConfig, event_bus: EventBus
    ) -> None:
        custom_ib = MagicMock()
        custom_ib.connectAsync = AsyncMock()
        custom_ib.disconnectedEvent = MagicMock()
        custom_ib.disconnectedEvent.connect.return_value = "hid"
        custom_ib.connectedEvent = MagicMock()

        cl = IBKRClient(
            config=broker_config,
            event_bus=event_bus,
            ib=custom_ib,
            heartbeat_interval=0.05,
        )
        await cl.connect()
        await cl.disconnect()
        assert cl.is_connected is False


class TestIBKRClientDisconnect:
    async def test_disconnect_cleanup(
        self, connected_client: IBKRClient, mock_ib: MagicMock
    ) -> None:
        await connected_client.disconnect()
        assert connected_client.is_connected is False
        assert connected_client._heartbeat_task is None
        mock_ib.disconnect.assert_called_once()

    async def test_disconnect_removes_handler(
        self, connected_client: IBKRClient, mock_ib: MagicMock
    ) -> None:
        await connected_client.disconnect()
        mock_ib.disconnectedEvent.disconnect.assert_called_once_with("handler_id")

    async def test_disconnect_when_not_connected(self, client: IBKRClient) -> None:
        await client.disconnect()
        assert client.is_connected is False

    async def test_disconnect_cancels_reconnect_task(self, connected_client: IBKRClient) -> None:
        connected_client._reconnect_task = asyncio.get_event_loop().create_future()
        await connected_client.disconnect()
        assert connected_client._reconnect_task is None

    async def test_disconnect_idempotent(self, client: IBKRClient) -> None:
        await client.disconnect()
        await client.disconnect()
        assert client.is_connected is False


class TestIBKRClientReconnect:
    async def test_reconnect_loop_success(
        self, client: IBKRClient, mock_ib: MagicMock, event_bus: EventBus
    ) -> None:
        await client.connect()
        await event_bus.drain()

        mock_ib.connectAsync.side_effect = [
            ConnectionRefusedError("fail"),
            None,
        ]
        client._connected = False

        client._reconnect_task = asyncio.create_task(client._reconnect_loop())
        await asyncio.sleep(0.2)
        await event_bus.drain()

        assert client.is_connected is True

    async def test_reconnect_loop_max_attempts_exceeded(
        self, client: IBKRClient, mock_ib: MagicMock, event_bus: EventBus
    ) -> None:
        client._config.max_reconnect_attempts = 2
        mock_ib.isConnected.return_value = False
        await client.connect()
        await event_bus.drain()

        mock_ib.connectAsync.side_effect = ConnectionRefusedError("fail")
        client._connected = False

        client._reconnect_task = asyncio.create_task(client._reconnect_loop())
        await asyncio.sleep(0.3)
        await event_bus.drain()

        assert client.is_connected is False
        assert client._reconnect_task is None

    async def test_reconnect_disconnects_before_retry(
        self, client: IBKRClient, mock_ib: MagicMock
    ) -> None:
        await client.connect()
        client._connected = False
        mock_ib.connectAsync.side_effect = ConnectionRefusedError("fail")

        client._reconnect_task = asyncio.create_task(client._reconnect_loop())
        await asyncio.sleep(0.2)

        assert mock_ib.disconnect.called

    async def test_reconnect_skips_if_already_connected(
        self, client: IBKRClient, mock_ib: MagicMock
    ) -> None:
        await client.connect()
        client._reconnect_task = asyncio.create_task(client._reconnect_loop())
        await asyncio.sleep(0.1)

        initial_calls = mock_ib.connectAsync.call_count
        assert initial_calls == 1

    async def test_reconnect_not_running_after_disconnect(self, client: IBKRClient) -> None:
        await client.connect()
        client._connected = False
        client._running = False
        client._reconnect_task = asyncio.create_task(client._reconnect_loop())
        await asyncio.sleep(0.1)
        assert client._reconnect_task is None


class TestIBKRClientDisconnectHandler:
    async def test_on_disconnected_async_emits_event(
        self,
        connected_client: IBKRClient,
        collected_events: list,
        event_bus: EventBus,
    ) -> None:
        await connected_client._on_disconnected_async()
        await event_bus.drain()

        disconnected = [e for e in collected_events if isinstance(e, BrokerDisconnectedEvent)]
        assert len(disconnected) >= 1
        assert disconnected[0].reason == "connection lost"

    async def test_on_disconnected_async_starts_reconnect(
        self, connected_client: IBKRClient
    ) -> None:
        await connected_client._on_disconnected_async()
        assert connected_client._reconnect_task is not None

    async def test_on_disconnected_async_sets_connected_false(
        self, connected_client: IBKRClient
    ) -> None:
        await connected_client._on_disconnected_async()
        assert connected_client.is_connected is False

    async def test_on_disconnected_async_skips_reconnect_when_stopped(
        self, connected_client: IBKRClient
    ) -> None:
        connected_client._running = False
        await connected_client._on_disconnected_async()
        assert connected_client._reconnect_task is None


class TestIBKRClientHeartbeat:
    async def test_heartbeat_emits_event(
        self, client: IBKRClient, collected_events: list, event_bus: EventBus
    ) -> None:
        await client.connect()
        await asyncio.sleep(0.1)
        await event_bus.drain()
        await client.disconnect()

        heartbeats = [e for e in collected_events if isinstance(e, HeartbeatEvent)]
        assert len(heartbeats) >= 1

    async def test_heartbeat_stops_on_disconnect(self, client: IBKRClient) -> None:
        await client.connect()
        await client.disconnect()
        await asyncio.sleep(0.1)
        assert client._heartbeat_task is None or client._heartbeat_task.done()

    async def test_heartbeat_updates_connected_on_check(
        self, client: IBKRClient, mock_ib: MagicMock, event_bus: EventBus
    ) -> None:
        mock_ib.isConnected.return_value = False
        await client.connect()
        client._connected = True
        await asyncio.sleep(0.1)
        await event_bus.drain()
        assert client.is_connected is False


class TestIBKRClientProperty:
    async def test_is_connected_initially_false(self, client: IBKRClient) -> None:
        assert client.is_connected is False

    async def test_is_connected_after_connect(self, client: IBKRClient) -> None:
        await client.connect()
        assert client.is_connected is True

    async def test_is_connected_after_disconnect(self, client: IBKRClient) -> None:
        await client.connect()
        await client.disconnect()
        assert client.is_connected is False
