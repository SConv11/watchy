"""Calibrate an ATR-adaptive Tier 2 proximity band (#15) against real data.

The Tier 2 gate currently skips a watch-only ticker on weekdays when price is
farther than a *fixed* percent (`min_price_proximity_pct`, default 8%) from its
entry target. This script explores making that band *per-ticker adaptive*:

    band_pct = mult * ATR%        where  ATR% = avg_atr_20d / price * 100

i.e. "skip when price is more than `mult` typical trading days of movement away
from the target". A volatile name gets a wider band (it can reach the target
fast — don't silence it early); a calm name gets a narrower one.

For every watchlist ticker it prints the current ATR%, the resulting band at a
range of candidate multiples (clamped to [FLOOR, CEILING]), and whether the
*current* price would be gated under each — next to the fixed-8% baseline — so
you can pick a `mult` from real numbers instead of guessing.

Read-only: no config/state/network writes. Run with the trading-env python
(needs yfinance; reads ~/watchy/state.db for #16 derived targets):

    /home/watchy/.pyenv/versions/3.11.9/envs/trading/bin/python \
        scripts/calibrate_atr_proximity.py

Optionally pass candidate multiples (default: 3 4 5 6 8):

    ... scripts/calibrate_atr_proximity.py 4 5 6
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from watchy.config import load_config
from watchy.indicators import compute_indicators
from watchy.proximity import is_outside_proximity
from watchy.state import StateStore

# Clamp bounds the live gate would apply to an ATR-derived band, so a freak
# low/high-volatility reading can't produce an absurd band. Keep in sync with
# the proposed WatchyConfig.proximity_pct_floor / _ceiling defaults.
FLOOR = 4.0
CEILING = 20.0

# The fixed baseline to compare against (today's global default).
FIXED_BASELINE = 8.0

DEFAULT_MULTS = [3.0, 4.0, 5.0, 6.0, 8.0]

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("calibrate_atr")


def _clamp(x: float) -> float:
    return max(FLOOR, min(CEILING, x))


def _effective_target(tc, state: dict) -> float | None:
    """Mirror tier2._effective_target: manual target_price wins, else #16 derived."""
    if tc is not None and getattr(tc, "target_price", None) is not None:
        return tc.target_price
    return state.get("derived_target_price")


def main(argv: list[str]) -> int:
    try:
        mults = [float(a) for a in argv] or DEFAULT_MULTS
    except ValueError:
        print(f"usage: {Path(__file__).name} [mult ...]   (e.g. 4 5 6)")
        return 2
    mults = mults or DEFAULT_MULTS

    try:
        config = load_config()
    except FileNotFoundError:
        print("Config not found — need ~/watchy/config.yaml (or WATCHY_CONFIG).")
        return 1

    store = StateStore()

    print(f"Clamp [{FLOOR:.0f}%, {CEILING:.0f}%]  |  baseline fixed = {FIXED_BASELINE:.0f}%")
    print(f"band_pct = mult x ATR%   (ATR% = avg_atr_20d / price x 100)\n")

    # Header
    mult_cols = "  ".join(f"x{m:g}" for m in mults)
    print(
        f"{'TICKER':<7} {'PRICE':>9} {'TARGET':>9} {'DIST%':>7} {'ATR%':>6}  "
        f"| band% per mult ({mult_cols})   | gate@fixed8 / gate@mult"
    )
    print("-" * 110)

    for tc in config.watchlist:
        ticker = tc.ticker
        bundle = compute_indicators(ticker)
        if bundle is None or bundle.current_price is None:
            print(f"{ticker:<7} (no indicator data)")
            continue

        price = bundle.current_price
        avg_atr = bundle.avg_atr_20d or bundle.atr
        state = store.get_ticker_state(ticker)
        target = _effective_target(tc, state)

        if not avg_atr or price <= 0:
            print(f"{ticker:<7} {price:>9.2f} (no usable ATR)")
            continue

        atr_pct = avg_atr / price * 100
        dist_pct = (abs(price - target) / target * 100) if target else None
        dist_s = f"{dist_pct:>6.1f}" if dist_pct is not None else "   n/a"
        target_s = f"{target:>9.2f}" if target else "   (none)"

        bands = [_clamp(m * atr_pct) for m in mults]
        bands_s = "  ".join(f"{b:>4.1f}" for b in bands)

        # "gate?" = would the CURRENT price be skipped under each band.
        if target is None:
            gate_fixed = "RUN(no-tgt)"
            gates = "  ".join("  - " for _ in mults)
        else:
            gate_fixed = "SKIP" if is_outside_proximity(price, target, FIXED_BASELINE) else "RUN"
            gates = "  ".join(
                ("SKIP" if is_outside_proximity(price, target, b) else " RUN")
                for b in bands
            )

        print(
            f"{ticker:<7} {price:>9.2f} {target_s} {dist_s} {atr_pct:>5.1f}  "
            f"| {bands_s}   | {gate_fixed:<11} {gates}"
        )

    print("\nLegend: DIST% = how far current price is from target; a ticker is")
    print("SKIPped when DIST% > band%. Pick the mult whose SKIP/RUN pattern best")
    print("matches which names you actually want analysed vs. gated for cost.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
