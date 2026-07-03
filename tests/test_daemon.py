"""Tests for the Tier 1 market-hours guard (#7)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from watchy.daemon import (
    _is_market_open,
    _is_tier2_day,
    _regular_session_window,
    _tier1_job,
    _tier2_job,
)


def _utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


class TestRegularSessionWindow:
    """Pure weekday + UTC-window fallback (deterministic, no calendar)."""

    # 2026-06-01 is a Monday, 2026-06-06/07 are Sat/Sun.
    def test_weekday_midsession_open(self):
        assert _regular_session_window(_utc(2026, 6, 1, 15, 0)) is True

    def test_weekday_before_open(self):
        assert _regular_session_window(_utc(2026, 6, 1, 13, 0)) is False

    def test_weekday_after_close(self):
        assert _regular_session_window(_utc(2026, 6, 1, 20, 1)) is False

    def test_open_boundary_inclusive(self):
        assert _regular_session_window(_utc(2026, 6, 1, 13, 30)) is True

    def test_close_boundary_inclusive(self):
        assert _regular_session_window(_utc(2026, 6, 1, 20, 0)) is True

    def test_saturday_closed(self):
        assert _regular_session_window(_utc(2026, 6, 6, 15, 0)) is False

    def test_sunday_closed(self):
        assert _regular_session_window(_utc(2026, 6, 7, 15, 0)) is False


class TestIsMarketOpen:
    def test_weekend_closed(self):
        assert _is_market_open(_utc(2026, 6, 7, 15, 0)) is False  # Sunday

    def test_holiday_aware_new_years_day(self):
        """New Year's Day is always a market holiday — must be closed even though
        it's a weekday (verifies the exchange-calendar path, not just weekday)."""
        pytest.importorskip("exchange_calendars")
        assert _is_market_open(_utc(2026, 1, 1, 15, 0)) is False

    def test_regular_session_open(self):
        pytest.importorskip("exchange_calendars")
        # 2026-01-02 is a Friday, normal session; 15:00 UTC = 10:00 EST.
        assert _is_market_open(_utc(2026, 1, 2, 15, 0)) is True


class TestTier1JobGuard:
    def _args(self):
        return ("NVDA", MagicMock(), MagicMock(), MagicMock())

    def test_skips_scan_when_market_closed(self):
        with patch("watchy.daemon._is_market_open", return_value=False), \
             patch("watchy.daemon.scan_ticker") as mock_scan:
            _tier1_job(*self._args())
        mock_scan.assert_not_called()

    def test_runs_scan_when_market_open(self):
        with patch("watchy.daemon._is_market_open", return_value=True), \
             patch("watchy.daemon.scan_ticker", return_value=[]) as mock_scan:
            _tier1_job(*self._args())
        mock_scan.assert_called_once()


class TestTier2DayGuard:
    # 2026-06-06 is a Saturday; 2026-06-07 Sunday; 2026-06-01..05 Mon–Fri
    # (all ordinary trading days). Tier 2 now runs only on trading days.
    def test_saturday_is_not_a_tier2_day(self):
        assert _is_tier2_day(_utc(2026, 6, 6, 11, 30)) is False

    def test_sunday_is_not_a_tier2_day(self):
        """Weekend runs were dropped — the weekly full-risk run rides the first
        trading day of the week instead (see market_calendar)."""
        assert _is_tier2_day(_utc(2026, 6, 7, 11, 30)) is False

    def test_weekdays_are_tier2_days(self):
        for d in range(1, 6):  # Mon–Fri
            assert _is_tier2_day(_utc(2026, 6, d, 11, 30)) is True

    def test_weekday_holiday_is_not_a_tier2_day(self):
        """July 3 2026 is a Friday but a NYSE holiday (Independence Day observed);
        Tier 2 must skip it (verifies the exchange-calendar path, not just weekday)."""
        pytest.importorskip("exchange_calendars")
        assert _is_tier2_day(_utc(2026, 7, 3, 11, 30)) is False

    def test_job_skips_when_not_a_tier2_day(self):
        with patch("watchy.daemon._is_tier2_day", return_value=False), \
             patch("watchy.daemon.run_daily_scan") as mock_scan:
            _tier2_job(MagicMock(), MagicMock(), MagicMock())
        mock_scan.assert_not_called()

    def test_job_runs_on_a_tier2_day(self):
        with patch("watchy.daemon._is_tier2_day", return_value=True), \
             patch("watchy.daemon.run_daily_scan") as mock_scan:
            _tier2_job(MagicMock(), MagicMock(), MagicMock())
        mock_scan.assert_called_once()
