"""Bot configuration — all settings in one place."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from options_bot.risk.manager import RiskLimits


@dataclass
class BrokerConfig:
    """Broker connection settings."""

    provider: str = "alpaca"  # "alpaca" or "paper"
    api_key: str = ""
    secret_key: str = ""
    paper: bool = True  # paper trading by default for safety

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("ALPACA_API_KEY", "")
        if not self.secret_key:
            self.secret_key = os.environ.get("ALPACA_SECRET_KEY", "")


@dataclass
class BotConfig:
    """Top-level bot configuration."""

    # Symbols to trade
    watchlist: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "AAPL", "TSLA", "AMZN", "MSFT", "NVDA"])

    # Capital
    initial_capital: float = 10_000.0

    # Scan interval in seconds
    scan_interval: int = 300  # 5 minutes

    # Which strategies are enabled
    enabled_strategies: list[str] = field(default_factory=lambda: [
        "bull_call_spread",
        "bear_put_spread",
        "bull_put_spread",
        "bear_call_spread",
        "iron_condor",
        "long_call",
        "long_put",
    ])

    # Preferred DTE range
    min_dte: int = 14
    max_dte: int = 45

    # Broker
    broker: BrokerConfig = field(default_factory=BrokerConfig)

    # Risk
    risk_limits: RiskLimits = field(default_factory=RiskLimits)

    # Logging
    log_level: str = "INFO"
    log_file: str = "options_bot.log"

    # Auto-trade or require confirmation
    auto_trade: bool = False  # require manual confirmation by default
    max_auto_trades_per_day: int = 3

    @classmethod
    def from_file(cls, path: str | Path) -> BotConfig:
        """Load config from a JSON file."""
        with open(path) as f:
            data = json.load(f)

        broker_data = data.pop("broker", {})
        risk_data = data.pop("risk_limits", {})

        config = cls(**data)
        config.broker = BrokerConfig(**broker_data)
        config.risk_limits = RiskLimits(**risk_data)
        return config

    def to_file(self, path: str | Path) -> None:
        """Save config to a JSON file."""
        data = {
            "watchlist": self.watchlist,
            "initial_capital": self.initial_capital,
            "scan_interval": self.scan_interval,
            "enabled_strategies": self.enabled_strategies,
            "min_dte": self.min_dte,
            "max_dte": self.max_dte,
            "auto_trade": self.auto_trade,
            "max_auto_trades_per_day": self.max_auto_trades_per_day,
            "log_level": self.log_level,
            "log_file": self.log_file,
            "broker": {
                "provider": self.broker.provider,
                "paper": self.broker.paper,
            },
            "risk_limits": {
                "max_portfolio_risk_pct": self.risk_limits.max_portfolio_risk_pct,
                "max_total_risk_pct": self.risk_limits.max_total_risk_pct,
                "max_single_position_pct": self.risk_limits.max_single_position_pct,
                "max_positions": self.risk_limits.max_positions,
                "max_daily_trades": self.risk_limits.max_daily_trades,
                "max_daily_loss": self.risk_limits.max_daily_loss,
                "require_defined_risk": self.risk_limits.require_defined_risk,
            },
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
