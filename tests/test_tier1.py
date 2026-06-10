"""Tests for the Tier 1 scan.

Tier 1 is an unconditional safety net (the #5 price-proximity skip was removed):
during market hours it always reads state and runs signal detection, regardless of
how far price sits from any configured target. Cost is controlled by which signals
fire the LLM pipeline and by cooldowns, not by gating the cheap scan.
"""

from unittest.mock import MagicMock, patch

from watchy.config import TickerConfig, WatchyConfig
from watchy.indicators import IndicatorBundle
from watchy.tier1 import scan_ticker


def _bundle(price: float) -> IndicatorBundle:
    b = IndicatorBundle(ticker="AAPL")
    b.current_price = price
    return b


def _config(**ticker_kwargs) -> WatchyConfig:
    return WatchyConfig(watchlist=[TickerConfig(ticker="AAPL", **ticker_kwargs)])


class TestScanAlwaysRuns:
    def test_scan_runs_even_when_price_far_from_target(self):
        # A configured target no longer gates Tier 1 — the scan always proceeds.
        config = _config(target_price=180.0)
        store, notifier = MagicMock(), MagicMock()
        store.get_ticker_state.return_value = {}
        with patch("watchy.tier1.compute_indicators", return_value=_bundle(210.0)), \
             patch("watchy.tier1.detect_signals", return_value=[]):
            out = scan_ticker("AAPL", config, store, notifier)
        assert out == []
        store.get_ticker_state.assert_called_once()  # never skipped on proximity

    def test_scan_normal_without_target(self):
        config = _config()  # no target at all → still scans
        store, notifier = MagicMock(), MagicMock()
        store.get_ticker_state.return_value = {}
        with patch("watchy.tier1.compute_indicators", return_value=_bundle(210.0)), \
             patch("watchy.tier1.detect_signals", return_value=[]):
            scan_ticker("AAPL", config, store, notifier)
        store.get_ticker_state.assert_called_once()

    def test_scan_skips_only_when_no_indicator_data(self):
        config = _config(target_price=180.0)
        store, notifier = MagicMock(), MagicMock()
        with patch("watchy.tier1.compute_indicators", return_value=None):
            out = scan_ticker("AAPL", config, store, notifier)
        assert out == []
        store.get_ticker_state.assert_not_called()  # no data → nothing to scan
