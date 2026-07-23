"""Tests for take-profit core logic (#28) — pure functions, no LLM."""

from watchy.config import TakeProfitConfig, TickerConfig, WatchyConfig
from watchy.indicators import IndicatorBundle
from watchy.positions import Position
from watchy.take_profit import (
    atr_runway,
    build_guidance,
    bundle_avg_atr,
    effective_floor_pct,
    extract_upside_level,
    is_in_zone,
    position_gain_pct,
    suggest_limit,
)


class TestEffectiveFloor:
    def test_global_default(self):
        cfg = WatchyConfig(take_profit=TakeProfitConfig(floor_gain_pct=10.0))
        assert effective_floor_pct(TickerConfig(ticker="NVDA"), cfg) == 10.0

    def test_per_ticker_override(self):
        cfg = WatchyConfig(take_profit=TakeProfitConfig(floor_gain_pct=10.0))
        tc = TickerConfig(ticker="NVDA", take_profit_floor_gain_pct=20.0)
        assert effective_floor_pct(tc, cfg) == 20.0

    def test_none_ticker_uses_global(self):
        cfg = WatchyConfig(take_profit=TakeProfitConfig(floor_gain_pct=12.0))
        assert effective_floor_pct(None, cfg) == 12.0


class TestIsInZone:
    def test_crosses_floor(self):
        assert is_in_zone(10.0, 10.0) is True
        assert is_in_zone(15.7, 10.0) is True

    def test_below_floor(self):
        assert is_in_zone(9.9, 10.0) is False

    def test_none_gain_never_in_zone(self):
        assert is_in_zone(None, 10.0) is False

    def test_loss_never_in_zone(self):
        assert is_in_zone(-5.0, 10.0) is False


class TestPositionGainPct:
    def test_reads_derived_pct(self):
        pos = Position(ticker="NVDA", quantity=3, average_cost=100.0)
        pos.unrealized_pnl_pct = 15.7
        assert position_gain_pct(pos) == 15.7

    def test_none_position(self):
        assert position_gain_pct(None) is None

    def test_no_cost_basis_gives_none(self):
        pos = Position(ticker="NVDA", quantity=3, average_cost=100.0)
        # _derive_pnl never ran → pct stays None → zone cannot arm
        assert position_gain_pct(pos) is None


class TestBundleAvgAtr:
    def test_prefers_20d(self):
        b = IndicatorBundle(ticker="X", atr=2.0, avg_atr_20d=5.0)
        assert bundle_avg_atr(b) == 5.0

    def test_falls_back_to_raw_atr(self):
        b = IndicatorBundle(ticker="X", atr=2.0, avg_atr_20d=None)
        assert bundle_avg_atr(b) == 2.0

    def test_none_bundle(self):
        assert bundle_avg_atr(None) is None


class TestAtrRunway:
    def test_basic(self):
        # (200 - 188) / 5 = 2.4 ATRs of room
        assert abs(atr_runway(188.0, 200.0, 5.0) - 2.4) < 1e-9

    def test_at_or_above_ceiling_is_zero(self):
        assert atr_runway(200.0, 200.0, 5.0) == 0.0
        assert atr_runway(205.0, 200.0, 5.0) == 0.0

    def test_missing_inputs_return_none(self):
        assert atr_runway(None, 200.0, 5.0) is None
        assert atr_runway(188.0, None, 5.0) is None
        assert atr_runway(188.0, 200.0, None) is None
        assert atr_runway(188.0, 200.0, 0.0) is None


class TestSuggestLimit:
    def test_price_plus_mult_atr(self):
        assert suggest_limit(180.0, 5.0, 1.5) == 187.5
        assert suggest_limit(180.0, 5.0, 3.0) == 195.0

    def test_missing_inputs(self):
        assert suggest_limit(None, 5.0, 1.5) is None
        assert suggest_limit(180.0, None, 1.5) is None
        assert suggest_limit(180.0, 0.0, 1.5) is None


class TestExtractUpsideLevel:
    def test_price_target_above_current(self):
        text = "Market Analyst sees a price target of $200 on continued strength."
        assert extract_upside_level(text, 188.0) == 200.0

    def test_resistance_level(self):
        text = "Key resistance at $210 caps the near-term move."
        assert extract_upside_level(text, 188.0) == 210.0

    def test_picks_nearest_above_current(self):
        text = "Targets: resistance $195, then upside target $230."
        # nearest ceiling above current is the immediate one
        assert extract_upside_level(text, 188.0) == 195.0

    def test_ignores_levels_below_current(self):
        text = "Support target at $150 holds; stop below."
        assert extract_upside_level(text, 188.0) is None

    def test_ignores_absurd_hits(self):
        text = "Long-run target $9000 someday."
        assert extract_upside_level(text, 188.0) is None

    def test_no_match_returns_none(self):
        assert extract_upside_level("No levels cited here.", 188.0) is None
        assert extract_upside_level("", 188.0) is None
        assert extract_upside_level("target $200", None) is None


class TestBuildGuidance:
    def _cfg(self):
        return TakeProfitConfig(
            enabled=True, floor_gain_pct=10.0, limit_atr_mult=1.5,
            stretch_atr_mult=3.0, runway_near_atr=1.0, runway_far_atr=2.5,
        )

    def test_small_runway_says_bank_now(self):
        # price 199, ceiling 200, ATR 5 → runway 0.2 ATR (< 1) → at the ceiling
        g = build_guidance("NVDA", 16.0, 199.0, 5.0, 200.0, self._cfg())
        assert "TAKE-PROFIT ZONE ACTIVE" in g
        assert "+16.0%" in g
        assert "RUNWAY IS SMALL" in g
        assert "Take-Profit:" in g  # instructs filling the output line

    def test_large_runway_says_let_it_run(self):
        # price 180, ceiling 220, ATR 5 → runway 8 ATRs (> 2.5) → room to run
        g = build_guidance("NVDA", 12.0, 180.0, 5.0, 220.0, self._cfg())
        assert "RUNWAY IS LARGE" in g
        assert "stretch limit" in g

    def test_moderate_runway(self):
        # price 188, ceiling 200, ATR 5 → runway 2.4 (between 1 and 2.5)
        g = build_guidance("NVDA", 14.0, 188.0, 5.0, 200.0, self._cfg())
        assert "RUNWAY IS MODERATE" in g

    def test_unknown_upside_degrades_to_atr_limit(self):
        g = build_guidance("NVDA", 14.0, 188.0, 5.0, None, self._cfg())
        assert "runway is unknown" in g.lower()
        assert "good-day-reachable" in g

    def test_whole_share_guard_present(self):
        g = build_guidance("NVDA", 16.0, 199.0, 5.0, 200.0, self._cfg())
        assert "WHOLE SHARES ONLY" in g
