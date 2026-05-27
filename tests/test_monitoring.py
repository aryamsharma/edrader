from __future__ import annotations

import time

import pytest

from edrader.events.bus import EventBus
from edrader.events.event_types import (
    AlertEvent,
    BrokerDisconnectedEvent,
    BrokerReconnectedEvent,
    ExposureUpdatedEvent,
    HeartbeatEvent,
    RiskViolationEvent,
    SignalRejectedEvent,
    TradingHaltedEvent,
)
from edrader.monitoring.alerts import AlertManager
from edrader.monitoring.metrics import MetricsCollector, RuntimeSnapshot


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


class TestRuntimeSnapshot:
    def test_default_values(self) -> None:
        snap = RuntimeSnapshot()
        assert snap.queue_depth == 0
        assert snap.subscriber_count == 0
        assert snap.throughput_1m == 0.0
        assert snap.total_published == 0
        assert snap.total_dispatched == 0
        assert snap.total_errors == 0
        assert snap.top_event_types == []
        assert snap.top_error_types == []

    def test_custom_values(self) -> None:
        snap = RuntimeSnapshot(
            queue_depth=5,
            subscriber_count=10,
            throughput_1m=100.0,
            total_published=1000,
            total_dispatched=950,
            total_errors=2,
            top_event_types=[("Tick", 500)],
            top_error_types=[("Tick", 1)],
        )
        assert snap.queue_depth == 5
        assert snap.throughput_1m == 100.0
        assert snap.top_event_types == [("Tick", 500)]


class TestMetricsCollector:
    async def test_initial_state(self, event_bus: EventBus) -> None:
        collector = MetricsCollector(event_bus=event_bus)
        assert collector.is_running is False

    async def test_lifecycle(self, event_bus: EventBus) -> None:
        collector = MetricsCollector(event_bus=event_bus)
        await collector.start()
        assert collector.is_running is True
        await collector.stop()
        assert collector.is_running is False

    async def test_start_idempotent(self, event_bus: EventBus) -> None:
        collector = MetricsCollector(event_bus=event_bus)
        await collector.start()
        await collector.start()
        assert collector.is_running is True
        await collector.stop()

    async def test_stop_idempotent(self, event_bus: EventBus) -> None:
        collector = MetricsCollector(event_bus=event_bus)
        await collector.stop()
        await collector.stop()
        assert collector.is_running is False

    async def test_snapshot_returns_metrics(self, event_bus: EventBus) -> None:
        collector = MetricsCollector(event_bus=event_bus, sample_interval=0.1)
        await collector.start()

        await event_bus.publish(
            ExposureUpdatedEvent(
                gross_exposure=0.0,
                net_exposure=0.0,
                leverage=0.0,
                long_count=0,
                short_count=0,
                equity=100_000.0,
                source="test",
            )
        )
        await event_bus.drain()

        snap = collector.snapshot()
        assert snap.total_published >= 1
        assert snap.subscriber_count >= 0
        assert isinstance(snap.queue_depth, int)

        await collector.stop()

    async def test_snapshot_after_no_events(self, event_bus: EventBus) -> None:
        collector = MetricsCollector(event_bus=event_bus, sample_interval=0.1)
        await collector.start()

        snap = collector.snapshot()
        assert snap.total_published == 0
        assert snap.throughput_1m == 0.0

        await collector.stop()


class TestAlertManager:
    async def test_initial_state(self, event_bus: EventBus) -> None:
        manager = AlertManager(event_bus=event_bus)
        assert manager.is_running is False

    async def test_lifecycle(self, event_bus: EventBus) -> None:
        manager = AlertManager(event_bus=event_bus)
        await manager.start()
        assert manager.is_running is True
        await manager.stop()
        assert manager.is_running is False

    async def test_start_idempotent(self, event_bus: EventBus) -> None:
        manager = AlertManager(event_bus=event_bus)
        await manager.start()
        await manager.start()
        assert manager.is_running is True
        await manager.stop()

    async def test_stop_idempotent(self, event_bus: EventBus) -> None:
        manager = AlertManager(event_bus=event_bus)
        await manager.stop()
        await manager.stop()
        assert manager.is_running is False

    async def test_disconnect_triggers_alert(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        manager = AlertManager(event_bus=event_bus, cooldown_seconds=0)
        await manager.start()

        await event_bus.publish(BrokerDisconnectedEvent(reason="connection_lost", source="test"))
        await event_bus.drain()

        alerts = [e for e in collected_events if isinstance(e, AlertEvent)]
        assert len(alerts) >= 1
        assert alerts[-1].alert_type == "broker_disconnected"
        assert alerts[-1].severity == "CRITICAL"
        await manager.stop()

    async def test_reconnect_triggers_alert(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        manager = AlertManager(event_bus=event_bus, cooldown_seconds=0)
        await manager.start()

        await event_bus.publish(BrokerReconnectedEvent(attempts=3, source="test"))
        await event_bus.drain()

        alerts = [e for e in collected_events if isinstance(e, AlertEvent)]
        assert len(alerts) >= 1
        assert alerts[-1].alert_type == "broker_reconnected"
        assert alerts[-1].severity == "INFO"
        await manager.stop()

    async def test_risk_violation_triggers_alert(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        manager = AlertManager(event_bus=event_bus, cooldown_seconds=0)
        await manager.start()

        await event_bus.publish(
            RiskViolationEvent(
                strategy_id="strat1",
                rule="max_position_size",
                reason="exceeded limit",
                source="test",
            )
        )
        await event_bus.drain()

        alerts = [e for e in collected_events if isinstance(e, AlertEvent)]
        assert len(alerts) >= 1
        assert alerts[-1].alert_type == "risk_violation_max_position_size"
        assert alerts[-1].severity == "ERROR"
        await manager.stop()

    async def test_signal_rejected_triggers_alert(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        manager = AlertManager(event_bus=event_bus, cooldown_seconds=0)
        await manager.start()

        await event_bus.publish(
            SignalRejectedEvent(strategy_id="strat1", reason="kill_switch", source="test")
        )
        await event_bus.drain()

        alerts = [e for e in collected_events if isinstance(e, AlertEvent)]
        assert len(alerts) >= 1
        assert alerts[-1].alert_type == "signal_rejected"
        assert alerts[-1].severity == "WARNING"
        await manager.stop()

    async def test_trading_halted_triggers_alert(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        manager = AlertManager(event_bus=event_bus, cooldown_seconds=0)
        await manager.start()

        await event_bus.publish(TradingHaltedEvent(reason="kill_switch", source="test"))
        await event_bus.drain()

        alerts = [e for e in collected_events if isinstance(e, AlertEvent)]
        assert len(alerts) >= 1
        assert alerts[-1].alert_type == "trading_halted"
        assert alerts[-1].severity == "CRITICAL"
        await manager.stop()

    async def test_deduplication_suppresses_duplicate_alerts(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        manager = AlertManager(event_bus=event_bus, cooldown_seconds=60.0)
        await manager.start()

        for _ in range(3):
            await event_bus.publish(
                BrokerDisconnectedEvent(reason="connection_lost", source="test")
            )
        await event_bus.drain()

        alerts = [e for e in collected_events if isinstance(e, AlertEvent)]
        assert len(alerts) == 1
        await manager.stop()

    async def test_different_types_not_deduplicated(
        self, event_bus: EventBus, collected_events: list
    ) -> None:
        manager = AlertManager(event_bus=event_bus, cooldown_seconds=60.0)
        await manager.start()

        await event_bus.publish(BrokerDisconnectedEvent(reason="lost", source="test"))
        await event_bus.publish(TradingHaltedEvent(reason="kill_switch", source="test"))
        await event_bus.drain()

        alerts = [e for e in collected_events if isinstance(e, AlertEvent)]
        assert len(alerts) == 2
        await manager.stop()

    async def test_no_alerts_before_start(self, event_bus: EventBus) -> None:
        manager = AlertManager(event_bus=event_bus, cooldown_seconds=0)
        await event_bus.publish(BrokerDisconnectedEvent(reason="connection_lost", source="test"))
        await event_bus.drain()
        assert len(manager._last_alert_time) == 0

    async def test_alert_event_dataclass(self) -> None:
        event = AlertEvent(
            alert_type="test_type",
            message="test message",
            severity="CRITICAL",
            source="test",
        )
        assert event.alert_type == "test_type"
        assert event.message == "test message"
        assert event.severity == "CRITICAL"

    async def test_heartbeat_resets_alert(self, event_bus: EventBus) -> None:
        manager = AlertManager(
            event_bus=event_bus,
            cooldown_seconds=0,
            heartbeat_timeout=0.1,
        )
        await manager.start()

        manager._last_heartbeat = time.monotonic() - 10.0
        manager._alerted_no_heartbeat = True

        await event_bus.publish(HeartbeatEvent(source="test"))
        await event_bus.drain()

        assert manager._alerted_no_heartbeat is False
        await manager.stop()
