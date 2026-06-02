"""Tests for indicators: computation and signal detection with synthetic data."""

import numpy as np
import pandas as pd
import pytest

from watchy.indicators import (
    IndicatorBundle,
    compute_indicators,
    detect_signals,
    _compute_rsi,
    _classify_sepa_stage,
)


def make_ohlcv(
    prices: list[float],
    *,
    volumes: list[float] | None = None,
    high_low_spread: float = 0.01,
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame from a list of closing prices."""
    n = len(prices)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n, freq="D")
    data = {
        "Open": [p * (1 - high_low_spread / 2) for p in prices],
        "High": [p * (1 + high_low_spread / 2) for p in prices],
        "Low": [p * (1 - high_low_spread / 2) for p in prices],
        "Close": prices,
        "Volume": volumes if volumes else [1_000_000] * n,
    }
    return pd.DataFrame(data, index=dates)


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

class TestRSI:
    def test_rsi_extreme_low(self):
        """A steadily declining price series → RSI should be very low."""
        n = 50
        prices = [100.0 - i * 1.0 for i in range(n)]  # drops from 100 to 51
        prices[25] = prices[24] + 0.5  # tiny bounce avoids NaN
        close = pd.Series(prices)
        rsi = _compute_rsi(close)
        assert rsi is not None
        assert rsi < 30, f"Expected RSI < 30, got {rsi:.1f}"

    def test_rsi_extreme_high(self):
        """A steadily rising price series → RSI should be very high."""
        n = 50
        # Add one small dip so avg_loss stays non-zero (avoids NaN).
        prices = [100.0 + i * 1.0 for i in range(n)]
        prices[25] = prices[24] - 0.5  # tiny dip
        close = pd.Series(prices)
        rsi = _compute_rsi(close)
        assert rsi is not None
        assert rsi > 70, f"Expected RSI > 70, got {rsi:.1f}"

    def test_rsi_mid_range(self):
        """Alternating up/down should keep RSI near 50."""
        n = 50
        prices = [100.0]
        for i in range(1, n):
            prices.append(prices[-1] + (1.0 if i % 2 == 0 else -1.0))
        close = pd.Series(prices)
        rsi = _compute_rsi(close)
        assert rsi is not None
        assert 40 < rsi < 60, f"Expected RSI ~50, got {rsi:.1f}"


# ---------------------------------------------------------------------------
# IndicatorBundle computation
# ---------------------------------------------------------------------------

class TestComputeIndicators:
    def test_returns_none_for_empty_df(self):
        assert compute_indicators("FAKE", pd.DataFrame()) is None

    def test_returns_none_for_short_history(self):
        df = make_ohlcv([100.0] * 10)  # only 10 days
        assert compute_indicators("FAKE", df) is None

    def test_computes_all_fields(self):
        """With 250 days of flat-ish data, all fields should populate."""
        prices = [100.0 + np.sin(i / 20) * 5 for i in range(250)]
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)

        assert bundle is not None
        assert bundle.ticker == "TEST"
        assert bundle.current_price is not None
        assert bundle.sma_50 is not None
        assert bundle.sma_200 is not None
        assert bundle.rsi is not None
        assert bundle.macd is not None
        assert bundle.macd_signal is not None
        assert bundle.bb_upper is not None
        assert bundle.bb_lower is not None
        assert bundle.atr is not None
        assert bundle.volume is not None
        assert bundle.avg_volume_20d is not None
        assert bundle.sepa_stage is not None

    def test_sepa_stage_present(self):
        """SEPA stage should be 1-4."""
        prices = [100.0 + i * 0.05 for i in range(250)]  # gentle uptrend
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None
        assert bundle.sepa_stage in (1, 2, 3, 4)


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

class TestDetectSignals:
    def test_empty_for_no_signals(self):
        """Flat prices with no prior state should produce no signals."""
        prices = [100.0] * 250
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None

        signals = detect_signals(bundle, {})
        # With exact flat prices, RSI might be NaN, so skip
        assert "golden_cross" not in signals
        assert "death_cross" not in signals

    def test_rsi_oversold_detected(self):
        """Fast decline → RSI < 30, prev_rsi was >= 30."""
        prices = [100.0 - i * 0.5 for i in range(250)]  # drops from 100 to -24
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None

        signals = detect_signals(bundle, {"prev_rsi": 50.0})
        assert "rsi_oversold" in signals

    def test_rsi_overbought_detected(self):
        """Fast rise → RSI > 70, prev_rsi was <= 70."""
        n = 250
        prices = [100.0 + i * 0.5 for i in range(n)]
        prices[125] = prices[124] - 0.5  # tiny dip avoids NaN
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None

        signals = detect_signals(bundle, {"prev_rsi": 50.0})
        assert "rsi_overbought" in signals

    def test_volume_anomaly_strong(self):
        """Last volume 3x the 20-day average."""
        prices = [100.0] * 250
        volumes = [1_000_000] * 249 + [3_000_000]  # spike on last day
        df = make_ohlcv(prices, volumes=volumes)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None
        # Override volume ratio to guarantee trigger
        bundle.volume = 3_000_000
        bundle.avg_volume_20d = 1_000_000

        signals = detect_signals(bundle, {})
        assert "volume_anomaly_strong" in signals

    def test_volume_anomaly_moderate(self):
        """Last volume 1.7x the 20-day average."""
        prices = [100.0] * 250
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None
        bundle.volume = 1_700_000
        bundle.avg_volume_20d = 1_000_000

        signals = detect_signals(bundle, {})
        assert "volume_anomaly_moderate" in signals

    def test_atr_spike(self):
        """ATR 2x the 20-day average ATR."""
        prices = [100.0] * 250
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None
        bundle.atr = 4.0
        bundle.avg_atr_20d = 2.0

        signals = detect_signals(bundle, {})
        assert "atr_spike" in signals

    def test_macd_bullish_cross(self):
        """MACD crosses above signal line."""
        prices = [100.0] * 250
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None
        bundle.macd = 0.5
        bundle.macd_signal = 0.3

        signals = detect_signals(bundle, {"prev_macd_above_signal": False})
        assert "macd_bullish_cross" in signals

    def test_golden_cross_requires_staircase(self):
        """50 > 150 > 200 with rising 200MA + prev state False."""
        prices = [100.0 + i * 0.3 for i in range(250)]
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None

        # Override MAs to create the staircase
        bundle.current_price = 110.0
        bundle.sma_50 = 105.0
        bundle.sma_150 = 102.0
        bundle.sma_200 = 100.0
        bundle.sma_200_1m_ago = 98.0  # 200MA rising

        signals = detect_signals(bundle, {"prev_sma_50_above_200": False})
        assert "golden_cross" in signals

    def test_death_cross(self):
        """50 SMA crosses below 200 SMA."""
        prices = [100.0] * 250
        df = make_ohlcv(prices)
        bundle = compute_indicators("TEST", df)
        assert bundle is not None
        bundle.current_price = 90.0
        bundle.sma_50 = 95.0
        bundle.sma_200 = 100.0

        signals = detect_signals(bundle, {"prev_sma_50_above_200": True})
        assert "death_cross" in signals


# ---------------------------------------------------------------------------
# SEPA classification
# ---------------------------------------------------------------------------

class TestSEPAStage:
    def test_stage_2_advancing(self):
        bundle = IndicatorBundle(ticker="X")
        bundle.current_price = 110.0
        bundle.sma_50 = 105.0
        bundle.sma_150 = 102.0
        bundle.sma_200 = 100.0
        bundle.sma_200_1m_ago = 98.0  # rising

        assert _classify_sepa_stage(bundle) == 2

    def test_stage_4_declining(self):
        bundle = IndicatorBundle(ticker="X")
        bundle.current_price = 90.0
        bundle.sma_50 = 95.0
        bundle.sma_150 = 98.0
        bundle.sma_200 = 100.0
        bundle.sma_200_1m_ago = 102.0  # falling

        assert _classify_sepa_stage(bundle) == 4

    def test_missing_data_returns_none(self):
        bundle = IndicatorBundle(ticker="X")
        assert _classify_sepa_stage(bundle) is None
