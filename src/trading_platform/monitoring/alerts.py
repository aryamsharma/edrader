from __future__ import annotations

import asyncio
import time
from typing import Any

from trading_platform.events.bus import EventBus
from trading_platform.events.event_types import (
    AlertEvent,
    BaseEvent,
    BrokerDisconnectedEvent,
    BrokerReconnectedEvent,
    HeartbeatEvent,
    RiskViolationEvent,
    SignalRejectedEvent,
    TradingHaltedEvent,
)
from trading_platform.monitoring.logging import get_logger

logger = get_logger(__name__)


class AlertManager:
    def __init__(
        self,
        event_bus: EventBus,
        cooldown_seconds: float = 60.0,
        heartbeat_timeout: float = 30.0,
    ) -> None:
        self._event_bus = event_bus
        self._cooldown_seconds = cooldown_seconds
        self._heartbeat_timeout = heartbeat_timeout
        self._running = False
        self._last_alert_time: dict[str, float] = {}
        self._last_heartbeat: float = 0.0
        self._alerted_no_heartbeat: bool = False
        self._disconnect_unsub: Any = None
        self._reconnect_unsub: Any = None
        self._risk_unsub: Any = None
        self._reject_unsub: Any = None
        self._halt_unsub: Any = None
        self._heartbeat_unsub: Any = None
        self._check_task: Any = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._disconnect_unsub = await self._subscribe(BrokerDisconnectedEvent, self._on_disconnect)
        self._reconnect_unsub = await self._subscribe(BrokerReconnectedEvent, self._on_reconnect)
        self._risk_unsub = await self._subscribe(RiskViolationEvent, self._on_risk_violation)
        self._reject_unsub = await self._subscribe(SignalRejectedEvent, self._on_rejected)
        self._halt_unsub = await self._subscribe(TradingHaltedEvent, self._on_halt)
        self._heartbeat_unsub = await self._subscribe(HeartbeatEvent, self._on_heartbeat)
        self._check_task = await self._start_heartbeat_check()
        logger.info("alert_manager_started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for unsub in (
            self._disconnect_unsub,
            self._reconnect_unsub,
            self._risk_unsub,
            self._reject_unsub,
            self._halt_unsub,
            self._heartbeat_unsub,
            self._check_task,
        ):
            if unsub is not None:
                unsub()
        self._disconnect_unsub = None
        self._reconnect_unsub = None
        self._risk_unsub = None
        self._reject_unsub = None
        self._halt_unsub = None
        self._heartbeat_unsub = None
        self._check_task = None
        logger.info("alert_manager_stopped")

    def _check_cooldown(self, alert_type: str) -> bool:
        now = time.monotonic()
        last = self._last_alert_time.get(alert_type, 0.0)
        if now - last < self._cooldown_seconds:
            return False
        self._last_alert_time[alert_type] = now
        return True

    async def _publish_alert(
        self, alert_type: str, message: str, severity: str = "WARNING"
    ) -> None:
        if not self._check_cooldown(alert_type):
            return
        await self._event_bus.publish(
            AlertEvent(
                alert_type=alert_type,
                message=message,
                severity=severity,
                source="alert_manager",
            )
        )
        logger.warning("alert_issued", alert_type=alert_type, severity=severity, message=message)

    async def _on_disconnect(self, event: BaseEvent) -> None:
        assert isinstance(event, BrokerDisconnectedEvent)
        if not self._running:
            return
        await self._publish_alert(
            "broker_disconnected",
            f"Broker disconnected: {event.reason}",
            severity="CRITICAL",
        )

    async def _on_reconnect(self, event: BaseEvent) -> None:
        assert isinstance(event, BrokerReconnectedEvent)
        if not self._running:
            return
        await self._publish_alert(
            "broker_reconnected",
            f"Broker reconnected after {event.attempts} attempts",
            severity="INFO",
        )

    async def _on_risk_violation(self, event: BaseEvent) -> None:
        assert isinstance(event, RiskViolationEvent)
        if not self._running:
            return
        await self._publish_alert(
            f"risk_violation_{event.rule}",
            f"Risk violation: {event.reason} (strategy={event.strategy_id})",
            severity="ERROR",
        )

    async def _on_rejected(self, event: BaseEvent) -> None:
        assert isinstance(event, SignalRejectedEvent)
        if not self._running:
            return
        await self._publish_alert(
            "signal_rejected",
            f"Signal rejected: {event.reason} (strategy={event.strategy_id})",
            severity="WARNING",
        )

    async def _on_halt(self, event: BaseEvent) -> None:
        assert isinstance(event, TradingHaltedEvent)
        if not self._running:
            return
        await self._publish_alert(
            "trading_halted",
            f"Trading halted: {event.reason}",
            severity="CRITICAL",
        )

    async def _on_heartbeat(self, event: BaseEvent) -> None:
        assert isinstance(event, HeartbeatEvent)
        if not self._running:
            return
        self._last_heartbeat = time.monotonic()
        self._alerted_no_heartbeat = False

    async def _check_heartbeat(self) -> None:
        if not self._running:
            return
        if self._last_heartbeat == 0.0:
            return
        elapsed = time.monotonic() - self._last_heartbeat
        if elapsed > self._heartbeat_timeout and not self._alerted_no_heartbeat:
            self._alerted_no_heartbeat = True
            await self._publish_alert(
                "heartbeat_missed",
                f"No heartbeat for {elapsed:.0f}s (timeout={self._heartbeat_timeout:.0f}s)",
                severity="ERROR",
            )

    async def _heartbeat_check_loop(self) -> None:
        while self._running:
            await self._check_heartbeat()
            await asyncio.sleep(self._heartbeat_timeout / 2)

    async def _start_heartbeat_check(self) -> Any:
        task = asyncio.create_task(self._heartbeat_check_loop())

        def cancel() -> None:
            task.cancel()

        return cancel

    async def _subscribe(self, event_type: type[BaseEvent], handler: Any) -> Any:
        async def wrapper(event: BaseEvent) -> None:
            await handler(event)

        self._event_bus.subscribe(event_type, wrapper, name=f"alert_{event_type.__name__}")
        return lambda: self._event_bus.unsubscribe(event_type, wrapper)
