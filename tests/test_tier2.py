"""Tests for Tier 2 inter-ticker throttle (#1) and batch ordering (#21).

The throttle now lives in the pre-fetch phase (one compute_indicators per
ticker, throttled), so these patch compute_indicators to avoid real yfinance
calls and stub the state lookup.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from watchy.config import TickerConfig, WatchyConfig
from watchy.tier2 import run_daily_scan


def _config(n_tickers: int, throttle: float = 2.0) -> WatchyConfig:
    return WatchyConfig(
        watchlist=[TickerConfig(ticker=f"T{i}") for i in range(n_tickers)],
        tier2_throttle_s=throttle,
    )


@contextmanager
def _patched(sleep_target=True):
    """Patch the network/data touchpoints so run_daily_scan stays offline."""
    with patch("watchy.tier2._run_ticker", return_value={"summary": "ok"}) as run, \
         patch("watchy.tier2.compute_indicators", return_value=None), \
         patch("watchy.tier2.time.sleep") as sleep:
        yield run, sleep


def _mocks():
    store, notifier = MagicMock(), MagicMock()
    store.get_ticker_state.return_value = {}
    return store, notifier


class TestTier2Throttle:
    def test_sleeps_between_tickers(self):
        config = _config(4)
        store, notifier = _mocks()

        with _patched() as (_run, mock_sleep):
            run_daily_scan(config, store, notifier)

        # one sleep between each pair of tickers (pre-fetch loop) → n-1 sleeps
        assert mock_sleep.call_count == 3
        for call in mock_sleep.call_args_list:
            assert call.args[0] == 2.0

    def test_no_sleep_for_single_ticker(self):
        config = _config(1)
        store, notifier = _mocks()

        with _patched() as (_run, mock_sleep):
            run_daily_scan(config, store, notifier)

        mock_sleep.assert_not_called()

    def test_zero_throttle_disables_sleep(self):
        config = _config(5, throttle=0.0)
        store, notifier = _mocks()

        with _patched() as (_run, mock_sleep):
            run_daily_scan(config, store, notifier)

        mock_sleep.assert_not_called()

    def test_all_tickers_still_processed(self):
        config = _config(3)
        store, notifier = _mocks()

        with _patched() as (mock_run, _sleep):
            results = run_daily_scan(config, store, notifier)

        assert mock_run.call_count == 3
        assert set(results.keys()) == {"T0", "T1", "T2"}
