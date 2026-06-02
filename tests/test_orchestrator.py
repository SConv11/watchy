"""Tests for orchestrator: PipelineSpec, signal→pipeline mapping, cooldown."""

import pytest

from watchy.orchestrator import (
    AnalystSet,
    DebateMode,
    PipelineSpec,
    RiskMode,
    SIGNAL_PIPELINE,
    _analyst_names,
    get_cooldown_hours,
    get_pipeline,
)


class TestAnalystNames:
    def test_none_returns_empty(self):
        assert _analyst_names(AnalystSet.NONE) == []

    def test_market_only(self):
        assert _analyst_names(AnalystSet.MARKET_ONLY) == ["market"]

    def test_market_sentiment(self):
        assert _analyst_names(AnalystSet.MARKET_SENTIMENT) == ["market", "sentiment"]

    def test_market_sentiment_news(self):
        assert _analyst_names(AnalystSet.MARKET_SENTIMENT_NEWS) == [
            "market", "sentiment", "news",
        ]

    def test_full(self):
        assert _analyst_names(AnalystSet.FULL) == [
            "market", "sentiment", "news", "fundamentals",
        ]


class TestGetPipeline:
    def test_known_signal_returns_spec(self):
        spec = get_pipeline("golden_cross")
        assert spec.analysts == AnalystSet.MARKET_SENTIMENT_NEWS
        assert spec.debate == DebateMode.BULL_BEAR
        assert spec.risk == RiskMode.FULL

    def test_rsi_oversold_is_simplified(self):
        spec = get_pipeline("rsi_oversold")
        assert spec.analysts == AnalystSet.MARKET_SENTIMENT
        assert spec.risk == RiskMode.SIMPLIFIED

    def test_scheduled_daily_is_full(self):
        spec = get_pipeline("scheduled_daily")
        assert spec.analysts == AnalystSet.FULL
        assert spec.debate == DebateMode.BULL_BEAR
        assert spec.risk == RiskMode.FULL

    def test_unknown_signal_falls_back(self):
        spec = get_pipeline("banana_split")
        assert spec.analysts == AnalystSet.MARKET_SENTIMENT
        assert spec.risk == RiskMode.SIMPLIFIED

    def test_all_signals_have_spec(self):
        """Every signal in the config should have a spec."""
        expected = {
            "scheduled_daily",
            "golden_cross", "death_cross",
            "rsi_oversold", "rsi_overbought",
            "macd_bullish_cross", "macd_bearish_cross",
            "bollinger_upper_breach", "bollinger_lower_breach",
            "volume_anomaly_strong", "volume_anomaly_moderate",
            "atr_spike",
        }
        assert set(SIGNAL_PIPELINE.keys()) == expected


class TestCooldownHours:
    def test_golden_cross_is_days_times_24(self):
        from watchy.config import CooldownConfig
        cfg = CooldownConfig(golden_cross_d=7)
        assert get_cooldown_hours("golden_cross", cfg) == 7 * 24

    def test_rsi_oversold(self):
        from watchy.config import CooldownConfig
        cfg = CooldownConfig(rsi_extreme_h=12)
        assert get_cooldown_hours("rsi_oversold", cfg) == 12

    def test_macd_cross(self):
        from watchy.config import CooldownConfig
        cfg = CooldownConfig(macd_cross_h=24)
        assert get_cooldown_hours("macd_bullish_cross", cfg) == 24

    def test_unknown_signal_defaults_to_4(self):
        from watchy.config import CooldownConfig
        cfg = CooldownConfig()
        assert get_cooldown_hours("banana_split", cfg) == 4.0
