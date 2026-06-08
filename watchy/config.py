"""YAML config loader for Watchy."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TickerConfig:
    ticker: str
    tier1_interval_h: float = 0.5
    tier2_time_utc: str = "11:30"
    # Optional per-ticker Tier 1 price-proximity skip (#5). When both are set,
    # Tier 1 skips the scan unless the current price is within
    # tier1_min_price_proximity_pct percent of target_price.
    target_price: float | None = None
    tier1_min_price_proximity_pct: float | None = None


@dataclass
class SignalThresholds:
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    volume_ratio_moderate: float = 1.5
    volume_ratio_strong: float = 2.0
    atr_ratio: float = 1.5


@dataclass
class CooldownConfig:
    rsi_extreme_h: int = 12
    macd_cross_h: int = 24
    bollinger_breach_h: int = 6
    volume_anomaly_h: int = 4
    atr_spike_h: int = 6
    golden_cross_d: int = 7


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_key: str = ""
    api_base: str | None = None
    deepseek_api_key: str = ""


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class SchwabConfig:
    api_key: str = ""          # Schwab app key
    api_secret: str = ""       # Schwab app secret
    account_id: str = ""       # account number to use; blank = first linked account
    enabled: bool = False
    callback_url: str = "https://127.0.0.1"
    tokens_path: str = "~/watchy_config/schwab_tokens.json"


@dataclass
class WatchyConfig:
    watchlist: list[TickerConfig] = field(default_factory=list)
    signal_thresholds: SignalThresholds = field(default_factory=SignalThresholds)
    cooldown: CooldownConfig = field(default_factory=CooldownConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    schwab: SchwabConfig = field(default_factory=SchwabConfig)
    log_level: str = "INFO"
    log_file: str = "~/watchy/watchy.log"
    # Seconds to sleep between tickers in a Tier 2 daily scan, to avoid a
    # burst of yfinance requests tripping rate limits (#1).
    tier2_throttle_s: float = 2.0

    def get_ticker_config(self, ticker: str) -> TickerConfig | None:
        """Return the TickerConfig for a symbol (case-insensitive), or None."""
        t = ticker.upper()
        for tc in self.watchlist:
            if tc.ticker.upper() == t:
                return tc
        return None

    @classmethod
    def from_yaml(cls, path: str | Path) -> WatchyConfig:
        path = Path(os.path.expanduser(path))
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path) as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        return cls(
            watchlist=[
                TickerConfig(**t) if isinstance(t, dict) else TickerConfig(ticker=t)
                for t in raw.get("watchlist", [])
            ],
            signal_thresholds=SignalThresholds(
                **raw.get("signal_thresholds", {})
            ),
            cooldown=CooldownConfig(**raw.get("cooldown", {})),
            llm=LLMConfig(**raw.get("llm", {})),
            telegram=TelegramConfig(**raw.get("telegram", {})),
            schwab=SchwabConfig(**raw.get("schwab", {})),
            log_level=raw.get("log_level", "INFO"),
            log_file=raw.get("log_file", "~/watchy/watchy.log"),
            tier2_throttle_s=raw.get("tier2_throttle_s", 2.0),
        )


def _merge_secrets(config: WatchyConfig, secrets_path: str) -> WatchyConfig:
    """Merge secrets.yaml into config — secrets override corresponding sections."""
    if not os.path.exists(secrets_path):
        return config

    with open(secrets_path) as f:
        secrets: dict[str, Any] = yaml.safe_load(f) or {}

    if "llm" in secrets:
        config.llm = LLMConfig(**secrets["llm"])
    if "telegram" in secrets:
        config.telegram = TelegramConfig(**secrets["telegram"])
    if "schwab" in secrets:
        config.schwab = SchwabConfig(**secrets["schwab"])

    return config


def load_config(path: str | None = None) -> WatchyConfig:
    if path is None:
        path = os.environ.get(
            "WATCHY_CONFIG", os.path.expanduser("~/watchy/config.yaml")
        )
    path = os.path.expanduser(path)
    config = WatchyConfig.from_yaml(path)

    # Secrets always live in ~/watchy_config/, never in the git repo
    secrets_path = os.path.expanduser("~/watchy_config/secrets.yaml")
    return _merge_secrets(config, secrets_path)
