from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from trading_platform.app.config import TradingConfig


@pytest.fixture
def default_config() -> TradingConfig:
    return TradingConfig()


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    config = {
        "app": {"environment": "paper", "log_level": "INFO"},
        "broker": {"port": 7497, "client_id": 42},
        "risk": {"max_daily_loss": 500.0},
    }
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


@pytest.fixture
def empty_config_path(tmp_path: Path) -> Path:
    path = tmp_path / "empty.yaml"
    with open(path, "w") as f:
        yaml.dump({}, f)
    return path
