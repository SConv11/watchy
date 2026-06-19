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


class TestRescanCap:
    """Tier 1 daily rescan cap (#23) — limits paid pipelines per ticker per UTC day."""

    def _fire(self, config, runs_today):
        """Drive a single signal trip; return (store, notifier)."""
        store, notifier = MagicMock(), MagicMock()
        store.get_ticker_state.return_value = {}
        store.is_in_cooldown.return_value = False
        store.start_run.return_value = 1
        store.count_tier1_runs_today.return_value = runs_today
        with patch("watchy.tier1.compute_indicators", return_value=_bundle(210.0)), \
             patch("watchy.tier1.detect_signals", return_value=["rsi_oversold"]), \
             patch("watchy.tier1.run_pipeline", return_value={"summary": "ok"}) as run, \
             patch("watchy.tier1.get_advice", return_value={}), \
             patch("watchy.tier1.get_position_source"), \
             patch("watchy.tier1.monitor_schwab"):
            scan_ticker("AAPL", config, store, notifier)
        return store, notifier, run

    def test_capped_skips_pipeline(self):
        config = _config(max_tier1_pipelines_per_day=2)
        store, notifier, run = self._fire(config, runs_today=2)
        run.assert_not_called()                    # no paid pipeline
        notifier.rescan_capped.assert_called_once()
        notifier.signal_fired.assert_not_called()
        store.log_signal.assert_called_once()      # breach still recorded (cooldown intact)

    def test_under_cap_runs_pipeline(self):
        config = _config(max_tier1_pipelines_per_day=2)
        store, notifier, run = self._fire(config, runs_today=1)
        run.assert_called_once()
        notifier.rescan_capped.assert_not_called()
        notifier.signal_fired.assert_called_once()

    def test_no_cap_when_unset(self):
        config = _config()  # global None, no per-ticker → never capped
        config.max_tier1_pipelines_per_day = None
        store, notifier, run = self._fire(config, runs_today=99)
        run.assert_called_once()
        notifier.rescan_capped.assert_not_called()

    def test_per_ticker_override_beats_global(self):
        config = _config(max_tier1_pipelines_per_day=5)
        config.max_tier1_pipelines_per_day = 1  # global=1, per-ticker=5 → per-ticker wins
        store, notifier, run = self._fire(config, runs_today=3)
        run.assert_called_once()                   # 3 < 5, still runs
        notifier.rescan_capped.assert_not_called()
