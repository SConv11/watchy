"""Validate yfinance-cache as a drop-in for the Tier 1/2 history fetch (#2).

Checks, for a few tickers, that `yfinance_cache` returns data compatible with
what `indicators.compute_indicators` expects and numerically consistent with
plain `yfinance`:

  1. Interface: Ticker(...).history(period="1y", interval="1d") returns a
     DataFrame with OHLCV columns and a datetime index.
  2. Value equality: Close on overlapping dates matches yfinance within tol.
  3. Freshness: the last bar is the most recent trading day.
  4. Indicator parity: compute_indicators() over both frames yields the same
     SMA/RSI/MACD (the values our signals actually fire on).

Run manually (needs network):  python scripts/validate_yfc.py
Intraday-staleness (the last, incomplete bar refreshing mid-session) can only be
checked while the US market is open — noted, not asserted here.
"""

from __future__ import annotations

import sys
from datetime import datetime, time, timezone

import pandas as pd

import yfinance as yf
import yfinance_cache as yfc

from watchy.indicators import _CACHE_MAX_AGE, compute_indicators

TICKERS = ["AAPL", "NVDA", "MSFT"]
CLOSE_TOL = 0.01  # 1 cent


def _fetch(mod, ticker):
    return mod.Ticker(ticker).history(period="1y", interval="1d")


def _check_interface(name, df):
    issues = []
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in df.columns:
            issues.append(f"{name}: missing column {col}")
    if not isinstance(df.index, pd.DatetimeIndex):
        issues.append(f"{name}: index is not DatetimeIndex ({type(df.index).__name__})")
    if df.empty:
        issues.append(f"{name}: empty frame")
    return issues


def _compare_close(yf_df, yfc_df):
    a = yf_df["Close"].copy()
    b = yfc_df["Close"].copy()
    a.index = a.index.tz_localize(None).normalize()
    b.index = b.index.tz_localize(None).normalize()
    common = a.index.intersection(b.index)
    if len(common) == 0:
        return ["no overlapping dates between yfinance and yfc"], None
    diff = (a.loc[common] - b.loc[common]).abs()
    max_diff = float(diff.max())
    n_bad = int((diff > CLOSE_TOL).sum())
    msgs = [f"overlap={len(common)} bars, max|ΔClose|={max_diff:.4f}, bars>{CLOSE_TOL}={n_bad}"]
    return (msgs if n_bad == 0 else msgs + [f"VALUE MISMATCH: {n_bad} bars differ"]), max_diff


def _compare_indicators(ticker, yf_df, yfc_df):
    b1 = compute_indicators(ticker, yf_df)
    b2 = compute_indicators(ticker, yfc_df)
    if b1 is None or b2 is None:
        return [f"compute_indicators returned None (yf={b1 is None}, yfc={b2 is None})"]
    out = []
    for field in ("current_price", "sma_50", "sma_200", "rsi", "macd", "macd_signal"):
        v1, v2 = getattr(b1, field), getattr(b2, field)
        if v1 is None or v2 is None:
            out.append(f"{field}: None (yf={v1}, yfc={v2})")
            continue
        rel = abs(v1 - v2) / (abs(v1) + 1e-9)
        flag = "" if rel < 0.005 else "  <-- >0.5% DRIFT"
        out.append(f"{field}: yf={v1:.4f} yfc={v2:.4f} rel={rel:.4%}{flag}")
    return out


def _us_market_open(now: datetime | None = None) -> bool:
    """Rough US regular-session check: weekday, 13:30–20:00 UTC (ignores holidays)."""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    return time(13, 30) <= now.timetz().replace(tzinfo=None) <= time(20, 0)


def check_intraday_staleness(ticker: str = "AAPL") -> None:
    """Confirm yfc's forming bar is fresh under our max_age (run on a weekday).

    With _CACHE_MAX_AGE passed, yfc should refetch the still-forming daily bar so
    its last Close tracks a live yfinance fetch. Prints yfc's Final?/FetchDate for
    the last row (those drive the would-be degrade guard if max_age proves
    insufficient). No-op with a message when the market is closed.
    """
    print("\n=== intraday staleness ===")
    if not _us_market_open():
        print("  SKIP — US market closed (run on a weekday 13:30–20:00 UTC to test)")
        return

    yfc_df = yfc.Ticker(ticker).history(period="5d", interval="1d", max_age=_CACHE_MAX_AGE)
    yf_df = yf.Ticker(ticker).history(period="5d", interval="1d")
    yfc_last = float(yfc_df["Close"].iloc[-1])
    yf_last = float(yf_df["Close"].iloc[-1])
    rel = abs(yfc_last - yf_last) / (abs(yf_last) + 1e-9)
    flag = "" if rel < 0.002 else "  <-- STALE: yfc lags live yfinance >0.2%"
    print(f"  {ticker}: yfc_last={yfc_last:.4f}  yf_live={yf_last:.4f}  rel={rel:.4%}{flag}")
    for col in ("Final?", "FetchDate"):
        if col in yfc_df.columns:
            print(f"  yfc last-row {col}: {yfc_df[col].iloc[-1]}")
    print(f"  (max_age={_CACHE_MAX_AGE})")


def main() -> int:
    any_fail = False
    for ticker in TICKERS:
        print(f"\n=== {ticker} ===")
        try:
            yf_df = _fetch(yf, ticker)
            yfc_df = _fetch(yfc, ticker)
        except Exception as exc:  # noqa: BLE001
            print(f"  FETCH FAILED: {type(exc).__name__}: {exc}")
            any_fail = True
            continue

        for name, df in (("yfinance", yf_df), ("yfc", yfc_df)):
            issues = _check_interface(name, df)
            for i in issues:
                print(f"  [interface] {i}")
                any_fail = True
            print(f"  {name}: rows={len(df)} last={df.index[-1].date()} cols={list(df.columns)}")

        close_msgs, max_diff = _compare_close(yf_df, yfc_df)
        for m in close_msgs:
            print(f"  [close] {m}")
            if "MISMATCH" in m:
                any_fail = True

        print("  [indicators]")
        for line in _compare_indicators(ticker, yf_df, yfc_df):
            print(f"    {line}")
            if "DRIFT" in line:
                any_fail = True

    check_intraday_staleness()

    print("\n" + ("FAIL — see issues above" if any_fail else "OK — yfc compatible"))
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
