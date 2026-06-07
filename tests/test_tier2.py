"""Tests for Tier 2 inter-ticker throttle (#1)."""

from unittest.mock import MagicMock, patch

from watchy.config import TickerConfig, WatchyConfig
from watchy.tier2 import run_daily_scan


def _config(n_tickers: int, throttle: float = 2.0) -> WatchyConfig:
    return WatchyConfig(
        watchlist=[TickerConfig(ticker=f"T{i}") for i in range(n_tickers)],
        tier2_throttle_s=throttle,
    )


class TestTier2Throttle:
    def test_sleeps_between_tickers(self):
        config = _config(4)
        store, notifier = MagicMock(), MagicMock()

        with patch("watchy.tier2._run_ticker", return_value={"summary": "ok"}), \
             patch("watchy.tier2.time.sleep") as mock_sleep:
            run_daily_scan(config, store, notifier)

        # one sleep between each pair of tickers → n-1 sleeps
        assert mock_sleep.call_count == 3
        for call in mock_sleep.call_args_list:
            assert call.args[0] == 2.0

    def test_no_sleep_for_single_ticker(self):
        config = _config(1)
        store, notifier = MagicMock(), MagicMock()

        with patch("watchy.tier2._run_ticker", return_value={"summary": "ok"}), \
             patch("watchy.tier2.time.sleep") as mock_sleep:
            run_daily_scan(config, store, notifier)

        mock_sleep.assert_not_called()

    def test_zero_throttle_disables_sleep(self):
        config = _config(5, throttle=0.0)
        store, notifier = MagicMock(), MagicMock()

        with patch("watchy.tier2._run_ticker", return_value={"summary": "ok"}), \
             patch("watchy.tier2.time.sleep") as mock_sleep:
            run_daily_scan(config, store, notifier)

        mock_sleep.assert_not_called()

    def test_all_tickers_still_processed(self):
        config = _config(3)
        store, notifier = MagicMock(), MagicMock()

        with patch("watchy.tier2._run_ticker", return_value={"summary": "ok"}) as mock_run, \
             patch("watchy.tier2.time.sleep"):
            results = run_daily_scan(config, store, notifier)

        assert mock_run.call_count == 3
        assert set(results.keys()) == {"T0", "T1", "T2"}
