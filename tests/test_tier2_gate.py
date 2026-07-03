"""Tests for the Tier 2 price-proximity gate (#15) and auto-derived target (#16)."""

from datetime import datetime, timezone

from types import SimpleNamespace

from watchy.advisor import _parse_advice, parse_price
from watchy.config import TickerConfig, WatchyConfig
from watchy.proximity import is_outside_proximity
from watchy.tier2 import (
    _PlanEntry,
    _effective_proximity_pct,
    _effective_target,
    _is_held,
    _ordered_run_plan,
    _should_skip_tier2,
)

# 2026-06-08 is a Monday — the first trading day of its week, i.e. the weekly
# full-risk run that is never gated. 2026-06-09 is a Tuesday — an ordinary
# trading day where the proximity gate applies. (Both agree under the
# calendar-less fallback: Monday == weekday 0, Tuesday != 0.)
WEEKLY_FULL_DAY = datetime(2026, 6, 8, tzinfo=timezone.utc)
GATED_DAY = datetime(2026, 6, 9, tzinfo=timezone.utc)


class TestIsOutsideProximity:
    def test_far_is_outside(self):
        assert is_outside_proximity(210.0, 180.0, 5.0) is True  # 16.7% away

    def test_near_is_inside(self):
        assert is_outside_proximity(184.0, 180.0, 5.0) is False  # 2.2% away

    def test_boundary_not_outside(self):
        assert is_outside_proximity(105.0, 100.0, 5.0) is False  # exactly 5%

    def test_unconfigured_never_outside(self):
        assert is_outside_proximity(999.0, None, 5.0) is False
        assert is_outside_proximity(999.0, 180.0, None) is False

    def test_no_price_or_bad_target(self):
        assert is_outside_proximity(None, 180.0, 5.0) is False
        assert is_outside_proximity(100.0, 0.0, 5.0) is False


class TestEffectiveTarget:
    def test_manual_target_wins(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        state = {"derived_target_price": 99.0}
        assert _effective_target(tc, state) == 180.0

    def test_derived_used_when_no_manual(self):
        tc = TickerConfig(ticker="AAPL")
        state = {"derived_target_price": 99.0}
        assert _effective_target(tc, state) == 99.0

    def test_none_when_neither(self):
        assert _effective_target(TickerConfig(ticker="AAPL"), {}) is None
        assert _effective_target(None, {}) is None


class TestShouldSkipTier2:
    def _tc(self, **kw):
        return TickerConfig(ticker="AAPL", min_price_proximity_pct=5.0, **kw)

    def test_weekday_far_not_held_skips(self):
        tc = self._tc(target_price=180.0)
        assert _should_skip_tier2(210.0, tc, {}, GATED_DAY, held=False) is True

    def test_held_never_skips(self):
        # even far + weekday + opted-in: a position we HOLD always runs
        tc = self._tc(target_price=180.0)
        assert _should_skip_tier2(210.0, tc, {}, GATED_DAY, held=True) is False

    def test_weekday_near_runs(self):
        tc = self._tc(target_price=180.0)
        assert _should_skip_tier2(184.0, tc, {}, GATED_DAY, held=False) is False

    def test_weekly_full_day_never_skips(self):
        # first trading day of the week (weekly full-risk run) → never gated
        tc = self._tc(target_price=180.0)
        assert _should_skip_tier2(210.0, tc, {}, WEEKLY_FULL_DAY, held=False) is False

    def test_no_pct_never_skips(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        assert _should_skip_tier2(210.0, tc, {}, GATED_DAY, held=False) is False

    def test_no_target_never_skips(self):
        # pct configured but neither manual nor derived target → can't gate
        assert _should_skip_tier2(210.0, self._tc(), {}, GATED_DAY, held=False) is False

    def test_uses_derived_target(self):
        # no manual target; a derived target far from price → skip on a gated day
        assert _should_skip_tier2(
            210.0, self._tc(), {"derived_target_price": 180.0}, GATED_DAY, held=False
        ) is True

    def test_no_ticker_config(self):
        assert _should_skip_tier2(210.0, None, {}, GATED_DAY, held=False) is False

    def test_global_default_applies_without_per_ticker(self):
        # no per-ticker pct, but a global default → gate applies on a gated day
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        cfg = WatchyConfig(min_price_proximity_pct=5.0)
        assert _should_skip_tier2(210.0, tc, {}, GATED_DAY, held=False, config=cfg) is True

    def test_per_ticker_overrides_global(self):
        # per-ticker 50% is lenient: 210 vs 180 (16.7%) is inside → runs, even
        # though the global 5% would have skipped it
        tc = TickerConfig(ticker="AAPL", target_price=180.0, min_price_proximity_pct=50.0)
        cfg = WatchyConfig(min_price_proximity_pct=5.0)
        assert _should_skip_tier2(210.0, tc, {}, GATED_DAY, held=False, config=cfg) is False

    def test_held_ignores_global_default(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        cfg = WatchyConfig(min_price_proximity_pct=5.0)
        assert _should_skip_tier2(210.0, tc, {}, GATED_DAY, held=True, config=cfg) is False

    def test_weekly_full_day_ignores_global_default(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        cfg = WatchyConfig(min_price_proximity_pct=5.0)
        assert _should_skip_tier2(210.0, tc, {}, WEEKLY_FULL_DAY, held=False, config=cfg) is False

    def test_atr_adaptive_gate_skips_when_outside_band(self):
        # ATR mult mode: avg_atr=3 on price 210 → ATR%≈1.43; mult 5 → band≈7.14%.
        # target 180, price 210 = 16.7% away > 7.14% → skip.
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        cfg = WatchyConfig(atr_proximity_mult=5.0)
        assert _should_skip_tier2(
            210.0, tc, {}, GATED_DAY, held=False, config=cfg, avg_atr=3.0
        ) is True

    def test_atr_adaptive_falls_back_to_fixed_without_atr(self):
        # mult set but no ATR data → fall back to the fixed global pct.
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        cfg = WatchyConfig(atr_proximity_mult=5.0, min_price_proximity_pct=50.0)
        # fixed 50% band: 16.7% away is inside → runs.
        assert _should_skip_tier2(
            210.0, tc, {}, GATED_DAY, held=False, config=cfg, avg_atr=None
        ) is False


class TestEffectiveProximityPct:
    def test_per_ticker_wins(self):
        tc = TickerConfig(ticker="AAPL", min_price_proximity_pct=12.0)
        assert _effective_proximity_pct(tc, WatchyConfig(min_price_proximity_pct=8.0)) == 12.0

    def test_global_when_no_per_ticker(self):
        cfg = WatchyConfig(min_price_proximity_pct=8.0)
        assert _effective_proximity_pct(TickerConfig(ticker="AAPL"), cfg) == 8.0

    def test_none_when_neither(self):
        assert _effective_proximity_pct(TickerConfig(ticker="AAPL"), WatchyConfig()) is None
        assert _effective_proximity_pct(None, None) is None

    def test_global_when_tc_none(self):
        assert _effective_proximity_pct(None, WatchyConfig(min_price_proximity_pct=8.0)) == 8.0

    # --- ATR-adaptive band (#15 follow-up) ---

    def test_atr_mult_overrides_fixed(self):
        # avg_atr=4, price=200 → ATR%=2.0; mult 5 → band 10.0%, beats fixed 8.
        tc = TickerConfig(ticker="AAPL")
        cfg = WatchyConfig(atr_proximity_mult=5.0, min_price_proximity_pct=8.0)
        assert _effective_proximity_pct(tc, cfg, avg_atr=4.0, price=200.0) == 10.0

    def test_per_ticker_mult_overrides_global_mult(self):
        tc = TickerConfig(ticker="AAPL", atr_proximity_mult=3.0)
        cfg = WatchyConfig(atr_proximity_mult=5.0)
        # ATR%=2.0 * mult 3 = 6.0
        assert _effective_proximity_pct(tc, cfg, avg_atr=4.0, price=200.0) == 6.0

    def test_atr_band_clamped_to_ceiling(self):
        # high volatility: ATR%=10, mult 5 → 50%, clamped to ceiling 20.
        cfg = WatchyConfig(atr_proximity_mult=5.0, proximity_pct_ceiling=20.0)
        assert _effective_proximity_pct(None, cfg, avg_atr=20.0, price=200.0) == 20.0

    def test_atr_band_clamped_to_floor(self):
        # ultra-calm: ATR%=0.1, mult 5 → 0.5%, clamped up to floor 4.
        cfg = WatchyConfig(atr_proximity_mult=5.0, proximity_pct_floor=4.0)
        assert _effective_proximity_pct(None, cfg, avg_atr=0.2, price=200.0) == 4.0

    def test_atr_falls_back_when_no_data(self):
        cfg = WatchyConfig(atr_proximity_mult=5.0, min_price_proximity_pct=8.0)
        assert _effective_proximity_pct(None, cfg, avg_atr=None, price=200.0) == 8.0
        assert _effective_proximity_pct(None, cfg, avg_atr=4.0, price=None) == 8.0


class TestOrderedRunPlan:
    def _entry(self, ticker, *, held=False, price=None, target=None):
        return _PlanEntry(
            ticker=ticker, tc=None, bundle=None, state={}, held=held,
            price=price, avg_atr=None, target=target, skip=False,
        )

    def test_held_first_then_nearest_then_no_target(self):
        plan = [
            self._entry("FAR", price=210.0, target=180.0),    # 16.7% away
            self._entry("NOTGT", price=50.0),                  # no target
            self._entry("HELD", held=True),                    # held
            self._entry("NEAR", price=182.0, target=180.0),    # 1.1% away
        ]
        order = [e.ticker for e in _ordered_run_plan(plan)]
        assert order == ["HELD", "NEAR", "FAR", "NOTGT"]

    def test_stable_within_no_target_group(self):
        plan = [self._entry("A"), self._entry("B"), self._entry("C")]
        assert [e.ticker for e in _ordered_run_plan(plan)] == ["A", "B", "C"]

    def test_held_beats_a_nearer_watch_ticker(self):
        plan = [
            self._entry("NEAR", price=181.0, target=180.0),  # 0.6% away
            self._entry("HELD", held=True, price=999.0, target=180.0),
        ]
        assert [e.ticker for e in _ordered_run_plan(plan)][0] == "HELD"


class TestIsHeld:
    def _src(self, get_position):
        return SimpleNamespace(get_position=get_position)

    def test_held_when_nonzero_quantity(self):
        src = self._src(lambda t: SimpleNamespace(quantity=50))
        assert _is_held(src, "AAPL") is True

    def test_not_held_when_none(self):
        src = self._src(lambda t: None)
        assert _is_held(src, "AAPL") is False

    def test_not_held_when_zero_quantity(self):
        src = self._src(lambda t: SimpleNamespace(quantity=0))
        assert _is_held(src, "AAPL") is False

    def test_lookup_error_treated_as_held(self):
        def boom(t):
            raise RuntimeError("schwab down")
        assert _is_held(self._src(boom), "AAPL") is True


class TestParsePrice:
    def test_plain_number(self):
        assert parse_price("215.50") == 215.50

    def test_dollar_sign(self):
        assert parse_price("$215.50") == 215.50

    def test_range_averages(self):
        assert parse_price("215-230") == 222.5

    def test_comma_thousands(self):
        assert parse_price("$3,000") == 3000.0

    def test_embedded_in_text(self):
        assert parse_price("around 180 on a pullback") == 180.0

    def test_na_and_empty(self):
        assert parse_price("N/A") is None
        assert parse_price("") is None
        assert parse_price(None) is None


class TestParseAdviceTarget:
    def test_captures_target_field(self):
        raw = (
            "Ticker: NVDA\nDecision: BUY\nUrgency: HIGH\nTarget: $215.50\n\n"
            "Accumulate on the pullback to support."
        )
        parsed = _parse_advice(raw, "NVDA")
        assert parsed["target"] == "$215.50"
        # the Target line must not bleed into the detail paragraph
        assert "215.50" not in parsed["detail"]
        assert parsed["detail"] == "Accumulate on the pullback to support."

    def test_missing_target_defaults_empty(self):
        raw = "Ticker: NVDA\nDecision: HOLD\nUrgency: LOW\n\nNothing actionable."
        parsed = _parse_advice(raw, "NVDA")
        assert parsed["target"] == ""
