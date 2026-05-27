from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from edrader.app.bootstrap import Application
from edrader.app.config import TradingConfig


@pytest.mark.asyncio
async def test_application_create_from_config() -> None:
    config = TradingConfig()
    app = Application(config)
    assert app.config.app.name == "trading-platform"
    assert not app.is_running


@pytest.mark.asyncio
async def test_application_startup_shutdown() -> None:
    config = TradingConfig()
    app = Application(config)

    assert not app.is_running
    await app.startup()
    assert app.is_running
    await app.shutdown()
    assert not app.is_running


@pytest.mark.asyncio
async def test_application_from_config_path(tmp_path: Path) -> None:
    config_path = tmp_path / "test_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"app": {"environment": "paper"}}, f)

    app = Application.from_config_path(config_path)
    assert app.config.app.environment == "paper"


@pytest.mark.asyncio
async def test_application_has_event_bus() -> None:
    config = TradingConfig()
    app = Application(config)
    assert app.event_bus is not None
    assert app.event_bus.queue_size == 0
    await app.startup()
    assert app.event_bus.queue_size == 0
    await app.shutdown()
