"""Tests for Tier 1 per-ticker price-proximity skip (#5)."""

from unittest.mock import MagicMock, patch

from watchy.config import TickerConfig, WatchyConfig
from watchy.indicators import IndicatorBundle
from watchy.tier1 import _is_outside_proximity, scan_ticker


def _bundle(price: float) -> IndicatorBundle:
    b = IndicatorBundle(ticker="AAPL")
    b.current_price = price
    return b


def _config(**ticker_kwargs) -> WatchyConfig:
    return WatchyConfig(watchlist=[TickerConfig(ticker="AAPL", **ticker_kwargs)])


class TestIsOutsideProximity:
    def test_far_is_outside(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0, tier1_min_price_proximity_pct=5.0)
        assert _is_outside_proximity(210.0, tc) is True  # 16.7% away

    def test_near_is_inside(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0, tier1_min_price_proximity_pct=5.0)
        assert _is_outside_proximity(184.0, tc) is False  # 2.2% away

    def test_exact_boundary_is_inside(self):
        tc = TickerConfig(ticker="AAPL", target_price=100.0, tier1_min_price_proximity_pct=5.0)
        assert _is_outside_proximity(105.0, tc) is False  # exactly 5% → not outside

    def test_unconfigured_never_skips(self):
        assert _is_outside_proximity(999.0, TickerConfig(ticker="AAPL")) is False

    def test_partial_config_never_skips(self):
        only_target = TickerConfig(ticker="AAPL", target_price=180.0)
        only_pct = TickerConfig(ticker="AAPL", tier1_min_price_proximity_pct=5.0)
        assert _is_outside_proximity(999.0, only_target) is False
        assert _is_outside_proximity(999.0, only_pct) is False

    def test_none_ticker_config(self):
        assert _is_outside_proximity(100.0, None) is False

    def test_no_price_never_skips(self):
        tc = TickerConfig(ticker="AAPL", target_price=180.0, tier1_min_price_proximity_pct=5.0)
        assert _is_outside_proximity(None, tc) is False


class TestScanTickerProximity:
    def test_scan_skips_when_far(self):
        config = _config(target_price=180.0, tier1_min_price_proximity_pct=5.0)
        store, notifier = MagicMock(), MagicMock()
        with patch("watchy.tier1.compute_indicators", return_value=_bundle(210.0)):
            out = scan_ticker("AAPL", config, store, notifier)
        assert out == []
        store.get_ticker_state.assert_not_called()  # skipped before reading state

    def test_scan_proceeds_when_near(self):
        config = _config(target_price=180.0, tier1_min_price_proximity_pct=5.0)
        store, notifier = MagicMock(), MagicMock()
        store.get_ticker_state.return_value = {}
        with patch("watchy.tier1.compute_indicators", return_value=_bundle(184.0)), \
             patch("watchy.tier1.detect_signals", return_value=[]):
            scan_ticker("AAPL", config, store, notifier)
        store.get_ticker_state.assert_called_once()  # not skipped

    def test_scan_normal_without_proximity_config(self):
        config = _config()  # no target/proximity → never skip
        store, notifier = MagicMock(), MagicMock()
        store.get_ticker_state.return_value = {}
        with patch("watchy.tier1.compute_indicators", return_value=_bundle(210.0)), \
             patch("watchy.tier1.detect_signals", return_value=[]):
            scan_ticker("AAPL", config, store, notifier)
        store.get_ticker_state.assert_called_once()
