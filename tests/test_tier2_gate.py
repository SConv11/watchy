"""Tests for the Tier 2 price-proximity gate (#15) and auto-derived target (#16)."""

from datetime import datetime, timezone

from types import SimpleNamespace

from watchy.advisor import _parse_advice, parse_price
from watchy.config import TickerConfig
from watchy.proximity import is_outside_proximity
from watchy.tier2 import (
    _effective_proximity_pct,
    _effective_target,
    _is_held,
    _should_skip_tier2,
)

# 2026-06-08 is a Monday (weekday 0); 2026-06-07 is a Sunday (weekday 6).
MONDAY = datetime(2026, 6, 8, tzinfo=timezone.utc)
SUNDAY = datetime(2026, 6, 7, tzinfo=timezone.utc)


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
        assert _should_skip_tier2(210.0, tc, {}, MONDAY, held=False) is True

    def test_held_never_skips(self):
        # even far + weekday + opted-in: a position we HOLD always runs
        tc = self._tc(target_price=180.0)
        assert _should_skip_tier2(210.0, tc, {}, MONDAY, held=True) is False

    def test_weekday_near_runs(self):
        tc = self._tc(target_price=180.0)
        assert _should_skip_tier2(184.0, tc, {}, MONDAY, held=False) is False

    def test_sunday_never_skips(self):
        tc = self._tc(target_price=180.0)
        assert _should_skip_tier2(210.0, tc, {}, SUNDAY, held=False) is False

    def test_no_pct_never_skips(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        assert _should_skip_tier2(210.0, tc, {}, MONDAY, held=False) is False

    def test_no_target_never_skips(self):
        # pct configured but neither manual nor derived target → can't gate
        assert _should_skip_tier2(210.0, self._tc(), {}, MONDAY, held=False) is False

    def test_uses_derived_target(self):
        # no manual target; a derived target far from price → skip on a weekday
        assert _should_skip_tier2(
            210.0, self._tc(), {"derived_target_price": 180.0}, MONDAY, held=False
        ) is True

    def test_no_ticker_config(self):
        assert _should_skip_tier2(210.0, None, {}, MONDAY, held=False) is False

    def test_global_default_applies_without_per_ticker(self):
        # no per-ticker pct, but a global default → gate applies on a weekday
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        assert _should_skip_tier2(
            210.0, tc, {}, MONDAY, held=False, global_pct=5.0
        ) is True

    def test_per_ticker_overrides_global(self):
        # per-ticker 50% is lenient: 210 vs 180 (16.7%) is inside → runs, even
        # though the global 5% would have skipped it
        tc = TickerConfig(ticker="AAPL", target_price=180.0, min_price_proximity_pct=50.0)
        assert _should_skip_tier2(
            210.0, tc, {}, MONDAY, held=False, global_pct=5.0
        ) is False

    def test_held_ignores_global_default(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        assert _should_skip_tier2(
            210.0, tc, {}, MONDAY, held=True, global_pct=5.0
        ) is False

    def test_sunday_ignores_global_default(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0)
        assert _should_skip_tier2(
            210.0, tc, {}, SUNDAY, held=False, global_pct=5.0
        ) is False


class TestEffectiveProximityPct:
    def test_per_ticker_wins(self):
        tc = TickerConfig(ticker="AAPL", min_price_proximity_pct=12.0)
        assert _effective_proximity_pct(tc, 8.0) == 12.0

    def test_global_when_no_per_ticker(self):
        assert _effective_proximity_pct(TickerConfig(ticker="AAPL"), 8.0) == 8.0

    def test_none_when_neither(self):
        assert _effective_proximity_pct(TickerConfig(ticker="AAPL"), None) is None
        assert _effective_proximity_pct(None, None) is None

    def test_global_when_tc_none(self):
        assert _effective_proximity_pct(None, 8.0) == 8.0


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
