"""Technical indicator calculations using yfinance + pandas-ta.

No LLM calls. No side effects. Independently testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class IndicatorBundle:
    ticker: str
    timestamp: pd.Timestamp | None = None
    # price
    current_price: float | None = None
    # moving averages
    sma_50: float | None = None
    sma_150: float | None = None
    sma_200: float | None = None
    sma_200_1m_ago: float | None = None  # for slope direction
    # RSI
    rsi: float | None = None
    # MACD
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    # Bollinger Bands
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    # ATR
    atr: float | None = None
    avg_atr_20d: float | None = None
    # Volume
    volume: float | None = None
    avg_volume_20d: float | None = None
    # SEPA stage classification
    sepa_stage: int | None = None  # 1=Basing, 2=Advancing, 3=Topping, 4=Declining
    # raw data for debugging
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def compute_indicators(
    ticker: str,
    history: pd.DataFrame | None = None,
) -> IndicatorBundle | None:
    """Compute all technical indicators for a ticker.

    Args:
        ticker: The ticker symbol.
        history: Optional pre-fetched OHLCV DataFrame (columns: Open, High, Low,
                 Close, Volume). If None, data is fetched from yfinance.

    Returns:
        IndicatorBundle with all computed values, or None if data unavailable.
    """
    try:
        df = history if history is not None else _fetch_history(ticker)
    except Exception:
        logger.exception("Failed to fetch data for %s", ticker)
        return None

    if df is None or df.empty or "Close" not in df.columns:
        logger.warning("No price data for %s", ticker)
        return None

    close: pd.Series = df["Close"]
    if len(close) < 200:
        logger.warning("Insufficient history for %s: %d rows", ticker, len(close))
        return None

    bundle = IndicatorBundle(ticker=ticker)
    bundle.timestamp = df.index[-1] if hasattr(df.index[-1], "isoformat") else None
    bundle.current_price = float(close.iloc[-1])

    # moving averages
    bundle.sma_50 = float(close.rolling(50).mean().iloc[-1])
    bundle.sma_150 = float(close.rolling(150).mean().iloc[-1])
    bundle.sma_200 = float(close.rolling(200).mean().iloc[-1])
    if len(close) >= 220:
        bundle.sma_200_1m_ago = float(close.rolling(200).mean().iloc[-21])

    # RSI
    bundle.rsi = _compute_rsi(close)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    bundle.macd = float(macd_line.iloc[-1])
    bundle.macd_signal = float(signal_line.iloc[-1])
    bundle.macd_histogram = float(macd_line.iloc[-1] - signal_line.iloc[-1])

    # Bollinger Bands (20-period, 2 std)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bundle.bb_middle = float(bb_mid.iloc[-1])
    bundle.bb_upper = float(bb_mid.iloc[-1] + 2 * bb_std.iloc[-1])
    bundle.bb_lower = float(bb_mid.iloc[-1] - 2 * bb_std.iloc[-1])

    # ATR (14-period)
    bundle.atr = _compute_atr(df)
    bundle.avg_atr_20d = float(
        pd.Series([_compute_atr(df, offset=i) for i in range(20)]).mean()
        if len(df) >= 34 else bundle.atr
    )

    # Volume
    if "Volume" in df.columns:
        bundle.volume = float(df["Volume"].iloc[-1])
        bundle.avg_volume_20d = float(df["Volume"].rolling(20).mean().iloc[-1])

    # SEPA stage classification
    bundle.sepa_stage = _classify_sepa_stage(bundle)

    return bundle


def detect_signals(
    bundle: IndicatorBundle,
    prev_state: dict,
) -> list[str]:
    """Detect which signals have fired given current indicators and previous state.

    Returns a list of signal type strings. Empty list means no signals.
    """
    signals: list[str] = []
    price = bundle.current_price
    if price is None:
        return signals

    # --- Golden Cross: 50 SMA crosses above 200 SMA + staircase forming ---
    sma50 = bundle.sma_50
    sma150 = bundle.sma_150
    sma200 = bundle.sma_200
    if sma50 and sma150 and sma200:
        prev_above = prev_state.get("prev_sma_50_above_200")
        now_above = sma50 > sma200
        # full staircase check: price > 50 > 150 > 200
        staircase = price > sma50 > sma150 > sma200
        # 200MA trending up
        sma200_rising = (
            bundle.sma_200_1m_ago is not None
            and sma200 > bundle.sma_200_1m_ago
        )
        if (
            prev_above is False
            and now_above
            and staircase
            and sma200_rising
        ):
            signals.append("golden_cross")

        # --- Death Cross: 50 SMA crosses below 200 SMA ---
        if prev_above is True and not now_above:
            signals.append("death_cross")

    # --- RSI extreme ---
    rsi = bundle.rsi
    if rsi is not None:
        prev_rsi = prev_state.get("prev_rsi")
        if rsi < 30 and (prev_rsi is None or prev_rsi >= 30):
            signals.append("rsi_oversold")
        elif rsi > 70 and (prev_rsi is None or prev_rsi <= 70):
            signals.append("rsi_overbought")

    # --- MACD crossover ---
    macd = bundle.macd
    macd_sig = bundle.macd_signal
    if macd is not None and macd_sig is not None:
        prev_above = prev_state.get("prev_macd_above_signal")
        now_above = macd > macd_sig
        if prev_above is False and now_above:
            signals.append("macd_bullish_cross")
        elif prev_above is True and not now_above:
            signals.append("macd_bearish_cross")

    # --- Bollinger Band breach ---
    if bundle.bb_upper and bundle.bb_lower:
        if price >= bundle.bb_upper:
            signals.append("bollinger_upper_breach")
        elif price <= bundle.bb_lower:
            signals.append("bollinger_lower_breach")

    # --- Volume anomaly ---
    vol = bundle.volume
    avg_vol = bundle.avg_volume_20d
    if vol and avg_vol and avg_vol > 0:
        ratio = vol / avg_vol
        if ratio >= 2.0:
            signals.append("volume_anomaly_strong")
        elif ratio >= 1.5:
            signals.append("volume_anomaly_moderate")

    # --- ATR spike ---
    atr = bundle.atr
    avg_atr = bundle.avg_atr_20d
    if atr and avg_atr and avg_atr > 0 and atr >= 1.5 * avg_atr:
        signals.append("atr_spike")

    return signals


def _fetch_history(ticker: str) -> pd.DataFrame | None:
    """Fetch OHLCV data from yfinance with rate-limit awareness."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return None

    try:
        t = yf.Ticker(ticker)
        df = t.history(period="1y", interval="1d")
        if df.empty:
            # retry with multi-ticker download
            df = yf.download(ticker, period="1y", interval="1d", progress=False)
        return df if not df.empty else None
    except Exception:
        raise


def _compute_rsi(close: pd.Series, period: int = 14) -> float | None:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    result = rsi.iloc[-1]
    return float(result) if not pd.isna(result) else None


def _compute_atr(df: pd.DataFrame, period: int = 14, offset: int = 0) -> float:
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    if offset:
        tr = tr.iloc[: len(tr) - offset]
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if not pd.isna(atr) else 0.0


def _classify_sepa_stage(bundle: IndicatorBundle) -> int | None:
    """Classify stock into SEPA stage 1-4 based on MA positions.

    Returns:
        1 = Basing, 2 = Advancing, 3 = Topping, 4 = Declining, None = insufficient data
    """
    p = bundle.current_price
    s50 = bundle.sma_50
    s150 = bundle.sma_150
    s200 = bundle.sma_200
    sma200_rising = (
        bundle.sma_200_1m_ago is not None
        and s200 is not None
        and s200 > bundle.sma_200_1m_ago
    )

    if not all([p, s50, s150, s200]):
        return None

    # Stage 2: Advancing — full bullish alignment
    if p > s50 > s150 > s200 and sma200_rising:
        return 2

    # Stage 4: Declining — bearish alignment
    if p < s200 and s50 < s200 and not sma200_rising:
        return 4

    # Stage 3: Topping — price near highs but MAs flattening
    if p > s200 and s50 > s200 and not sma200_rising:
        return 3

    # Stage 1: Basing — price consolidating around 200MA
    return 1
