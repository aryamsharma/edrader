from pathlib import Path

import pytest

from trading_platform.app.config import load_config


def test_load_default_config(default_config) -> None:
    assert default_config.app.name == "trading-platform"
    assert default_config.app.environment == "development"
    assert default_config.broker.port == 4001
    assert default_config.broker.client_id == 1
    assert default_config.risk.max_daily_loss == 1000.0


def test_load_config_from_file(config_path: Path) -> None:
    config = load_config(config_path)
    assert config.app.environment == "paper"
    assert config.app.log_level == "INFO"
    assert config.broker.port == 7497
    assert config.broker.client_id == 42
    assert config.risk.max_daily_loss == 500.0


def test_load_empty_config(empty_config_path: Path) -> None:
    config = load_config(empty_config_path)
    assert config.app.environment == "development"
    assert config.broker.port == 4001
    assert config.risk.max_position_size == 100


def test_load_config_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.yaml"))


def test_config_defaults_not_mutated(default_config) -> None:
    config = default_config
    assert config.risk.max_daily_loss == 1000.0
    assert config.persistence.database_url == "sqlite:///data/trading.db"
    assert config.monitoring.metrics_port == 9090


def test_invalid_environment_rejected() -> None:
    from pydantic import ValidationError

    from trading_platform.app.config import AppConfig

    with pytest.raises(ValidationError):
        AppConfig(environment="invalid")


def test_broker_config_defaults() -> None:
    from trading_platform.app.config import BrokerConfig

    config = BrokerConfig()
    assert config.host == "127.0.0.1"
    assert config.reconnect_interval == 5
    assert config.max_reconnect_attempts == 10


def test_risk_config_defaults() -> None:
    from trading_platform.app.config import RiskConfig

    config = RiskConfig()
    assert config.max_leverage == 2.0
    assert config.max_symbol_exposure == 50000.0
    assert config.max_concurrent_positions == 10
