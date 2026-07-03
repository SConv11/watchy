"""Tests for orchestrator: PipelineSpec, signal→pipeline mapping, cooldown."""

import pytest

from datetime import datetime, timezone

from watchy.orchestrator import (
    AnalystSet,
    DebateMode,
    PipelineSpec,
    RiskMode,
    SIGNAL_PIPELINE,
    _analyst_names,
    get_cooldown_hours,
    get_pipeline,
    get_scheduled_spec,
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

    def test_scheduled_daily_delegates_to_scheduled_spec(self):
        """get_pipeline('scheduled_daily') is day-dependent (always FULL analysts,
        BULL_BEAR debate; risk varies by weekday) — it is not a static entry."""
        spec = get_pipeline("scheduled_daily")
        assert spec.analysts == AnalystSet.FULL
        assert spec.debate == DebateMode.BULL_BEAR
        assert spec.risk in (RiskMode.FULL, RiskMode.SIMPLIFIED)
        assert "scheduled_daily" not in SIGNAL_PIPELINE

    def test_unknown_signal_falls_back(self):
        spec = get_pipeline("banana_split")
        assert spec.analysts == AnalystSet.MARKET_SENTIMENT
        assert spec.risk == RiskMode.SIMPLIFIED

    def test_all_signals_have_spec(self):
        """Every signal in the config should have a spec (scheduled_daily is not
        a signal — it's a day-dependent scheduled run, see get_scheduled_spec)."""
        expected = {
            "golden_cross", "death_cross",
            "rsi_oversold", "rsi_overbought",
            "macd_bullish_cross", "macd_bearish_cross",
            "bollinger_upper_breach", "bollinger_lower_breach",
            "volume_anomaly_strong",
            "atr_spike",
        }
        assert set(SIGNAL_PIPELINE.keys()) == expected


class TestScheduledSpec:
    """Tier 2 cadence: daily 4-analyst + weekly (first-trading-day) 3-way risk (#14)."""

    def test_first_trading_day_of_week_is_full_risk(self):
        # 2026-06-01 is a Monday and the first trading day of its week.
        monday = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        assert monday.weekday() == 0
        spec = get_scheduled_spec(monday)
        assert spec.analysts == AnalystSet.FULL
        assert spec.debate == DebateMode.BULL_BEAR
        assert spec.risk == RiskMode.FULL

    def test_midweek_is_simplified_risk(self):
        for d in range(2, 6):  # Tue(2026-06-02) .. Fri(2026-06-05)
            day = datetime(2026, 6, d, 12, 0, tzinfo=timezone.utc)
            assert day.weekday() not in (0, 6)
            spec = get_scheduled_spec(day)
            assert spec.analysts == AnalystSet.FULL
            assert spec.debate == DebateMode.BULL_BEAR
            assert spec.risk == RiskMode.SIMPLIFIED

    def test_full_risk_shifts_to_tuesday_when_monday_is_a_holiday(self):
        """Memorial Day 2026 (Mon 2026-05-25) is a NYSE holiday, so the weekly
        full-risk run shifts to Tuesday — the guarantee survives holiday Mondays."""
        pytest.importorskip("exchange_calendars")
        monday_holiday = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
        tuesday = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
        assert get_scheduled_spec(monday_holiday).risk == RiskMode.SIMPLIFIED
        assert get_scheduled_spec(tuesday).risk == RiskMode.FULL

    def test_analysts_always_full(self):
        """Fundamentals must be in the daily set (the gap #14 flagged)."""
        for d in range(1, 8):
            spec = get_scheduled_spec(datetime(2026, 6, d, 12, 0, tzinfo=timezone.utc))
            assert _analyst_names(spec.analysts) == [
                "market", "sentiment", "news", "fundamentals",
            ]


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
