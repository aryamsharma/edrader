from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from ib_async import IB

from edrader.app.config import BrokerConfig
from edrader.broker import task_error_logger
from edrader.events.bus import EventBus
from edrader.events.event_types import (
    BrokerDisconnectedEvent,
    BrokerReconnectedEvent,
    HeartbeatEvent,
)
from edrader.monitoring.logging import get_logger

logger = get_logger(__name__)


class IBKRClient:
    def __init__(
        self,
        config: BrokerConfig,
        event_bus: EventBus,
        ib: Any = None,
        heartbeat_interval: float = 5.0,
    ) -> None:
        self._config = config
        self._event_bus = event_bus
        self._ib: Any = ib if ib is not None else IB()  # type: ignore[no-untyped-call]
        self._connected = False
        self._running = False
        self._reconnect_attempts = 0
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._disconnect_handler: Any = None
        self._heartbeat_interval = heartbeat_interval

    async def connect(self) -> None:
        logger.info(
            "ibkr_connecting",
            host=self._config.host,
            port=self._config.port,
            client_id=self._config.client_id,
        )
        await self._ib.connectAsync(
            host=self._config.host,
            port=self._config.port,
            clientId=self._config.client_id,
            timeout=self._config.connect_timeout,
        )
        self._connected = True
        self._running = True
        self._reconnect_attempts = 0
        self._setup_handlers()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("ibkr_connected")
        await self._event_bus.publish(BrokerReconnectedEvent(attempts=0, source="ibkr_client"))

    async def disconnect(self) -> None:
        self._running = False
        tasks_to_await: list[asyncio.Task[None]] = []
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            tasks_to_await.append(self._heartbeat_task)
            self._heartbeat_task = None
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            tasks_to_await.append(self._reconnect_task)
            self._reconnect_task = None
        if self._disconnect_handler is not None:
            with contextlib.suppress(Exception):
                self._ib.disconnectedEvent.disconnect(self._disconnect_handler)
            self._disconnect_handler = None
        if self._ib.isConnected():
            self._ib.disconnect()
        self._connected = False
        for t in tasks_to_await:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        logger.info("ibkr_disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _setup_handlers(self) -> None:
        self._disconnect_handler = self._ib.disconnectedEvent.connect(self._on_disconnected)

    def _on_disconnected(self) -> None:
        task = asyncio.create_task(self._on_disconnected_async())
        task.add_done_callback(task_error_logger(__name__, "ibkr_background_task_failed"))

    async def _on_disconnected_async(self) -> None:
        self._connected = False
        logger.warning("ibkr_connection_lost")
        await self._event_bus.publish(
            BrokerDisconnectedEvent(reason="connection lost", source="ibkr_client")
        )
        if self._running and self._reconnect_task is None:
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        while self._running and not self._connected:
            self._reconnect_attempts += 1
            if self._reconnect_attempts > self._config.max_reconnect_attempts:
                logger.error(
                    "ibkr_max_reconnect_exceeded",
                    attempts=self._reconnect_attempts,
                )
                await self._event_bus.publish(
                    BrokerDisconnectedEvent(
                        reason=(
                            f"max reconnect attempts "
                            f"({self._config.max_reconnect_attempts}) exceeded"
                        ),
                        source="ibkr_client",
                    )
                )
                break
            await asyncio.sleep(self._config.reconnect_interval)
            logger.info(
                "ibkr_reconnect_attempt",
                attempt=self._reconnect_attempts,
                max_attempts=self._config.max_reconnect_attempts,
            )
            try:
                self._ib.disconnect()
                await self._ib.connectAsync(
                    host=self._config.host,
                    port=self._config.port,
                    clientId=self._config.client_id,
                    timeout=self._config.connect_timeout,
                )
                self._connected = True
                self._reconnect_attempts = 0
                self._setup_handlers()
                logger.info("ibkr_reconnected")
                await self._event_bus.publish(
                    BrokerReconnectedEvent(
                        attempts=self._reconnect_attempts,
                        source="ibkr_client",
                    )
                )
            except Exception as e:
                logger.warning(
                    "ibkr_reconnect_failed",
                    attempt=self._reconnect_attempts,
                    error=str(e),
                )
        self._reconnect_task = None

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                if self._ib.isConnected():
                    self._connected = True
                    await self._event_bus.publish(HeartbeatEvent(source="ibkr_client"))
                else:
                    self._connected = False
            except asyncio.CancelledError:
                break
            except Exception:
                pass
