from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class BrokerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4001
    client_id: int = 1
    connect_timeout: int = 30
    reconnect_interval: float = 5.0
    max_reconnect_attempts: int = 10


class RiskConfig(BaseModel):
    max_daily_loss: float = 1000.0
    max_position_size: int = 100
    max_leverage: float = 2.0
    max_symbol_exposure: float = 50000.0
    max_concurrent_positions: int = 10


class PersistenceConfig(BaseModel):
    database_url: str = "sqlite:///data/trading.db"
    echo: bool = False


class MonitoringConfig(BaseModel):
    metrics_enabled: bool = True
    metrics_port: int = 9090


class ExecutionConfig(BaseModel):
    sizing_method: str = "fixed"
    percent_equity_fraction: float = 0.02
    default_order_type: str = "MKT"
    max_retries: int = 3
    throttle_delay: float = 0.5


class AppConfig(BaseModel):
    name: str = "trading-platform"
    environment: Literal["development", "paper", "live"] = "development"
    log_level: str = "DEBUG"
    symbols: list[str] = Field(default_factory=list)


class TradingConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)


def load_config(path: Path) -> TradingConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raw = {}
    return TradingConfig(**raw)
