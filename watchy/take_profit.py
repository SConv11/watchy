"""Take-profit logic (#28) — mechanical gain-gate + ATR-runway helpers.

Pure, LLM-free functions. This protects unrealized gains on held winners — the
user's #1 pain: a position runs up, the gain isn't banked, and it round-trips.

The mechanical footprint is deliberately tiny. It decides only *when* to wake the
advisor up (unrealized gain crossed the floor) and hands it ground-truth facts —
the gain, the ATR "runway" left to the analysts' upside level, and a reachable
sell-limit price. The LLM then sizes the trim (whole shares) and sets the limit.
It is NOT asked to detect the top itself; that judgement is inconsistent (the
same data reads HOLD on one model and ADD on another) and the analysis often
still calls a top "strong". Feeding a mechanical fact sidesteps that. See #28.

The system is advisory-only: it emits "sell N shares at $X" and the user places
the limit order. A pre-set sell-limit above the market is what actually catches
the intraday high, so the daily cadence is enough as long as the limit is set
early — the Tier 1 zone-entry trigger exists to set it promptly (#28).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from watchy.config import TakeProfitConfig, TickerConfig, WatchyConfig
    from watchy.indicators import IndicatorBundle
    from watchy.positions import Position


def effective_floor_pct(tc: "TickerConfig | None", config: "WatchyConfig") -> float:
    """Take-profit floor for a ticker: per-ticker override else the global."""
    if tc is not None and tc.take_profit_floor_gain_pct is not None:
        return tc.take_profit_floor_gain_pct
    return config.take_profit.floor_gain_pct


def is_in_zone(gain_pct: float | None, floor_pct: float) -> bool:
    """True once a held position's unrealized gain has crossed the floor."""
    return gain_pct is not None and gain_pct >= floor_pct


def position_gain_pct(pos: "Position | None") -> float | None:
    """Unrealized gain % for a position, or None when it can't be computed.

    Needs a cost basis (``average_cost``) and a resolved ``unrealized_pnl_pct``
    (filled by positions._derive_pnl). None when not held or no cost basis — the
    take-profit zone can't arm without knowing the gain.
    """
    if pos is None:
        return None
    return pos.unrealized_pnl_pct


def bundle_avg_atr(bundle: "IndicatorBundle | None") -> float | None:
    """The ATR to size the trail/limit against — 20d average, else the raw ATR."""
    if bundle is None:
        return None
    return bundle.avg_atr_20d or bundle.atr


def atr_runway(
    price: float | None,
    upside_level: float | None,
    avg_atr: float | None,
) -> float | None:
    """ATRs of room left to the ceiling: (upside_level - price) / ATR.

    "How many typical trading days of movement remain before the cited upside /
    resistance level." None when the inputs are missing (→ runway unknown, the
    caller degrades to a pure ``price + k x ATR`` limit). 0.0 when price is at or
    above the level (already at the ceiling).
    """
    if not price or not avg_atr or avg_atr <= 0 or upside_level is None:
        return None
    if upside_level <= price:
        return 0.0
    return (upside_level - price) / avg_atr


def suggest_limit(price: float | None, avg_atr: float | None, mult: float) -> float | None:
    """A reachable sell-limit at ``price + mult x ATR``; None if inputs missing."""
    if not price or not avg_atr or avg_atr <= 0:
        return None
    return price + mult * avg_atr


# Labelled upside levels the analysts cite. Matches "price target", "target",
# "resistance", "upside" followed (within a short span) by a $-amount. Kept
# conservative on purpose: a miss degrades to a pure ATR limit, a false hit
# would mislead the runway, so we only trust clearly-labelled numbers.
_UPSIDE_RE = re.compile(
    r"(?:price\s+target|target|resistance|upside)[^.\n]{0,40}?"
    r"\$?\s*(\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)


def extract_upside_level(analysis_text: str, current_price: float | None) -> float | None:
    """Best-effort nearest upside/resistance level strictly ABOVE current price.

    Scans the analyst digest for clearly-labelled target/resistance prices and
    returns the closest one above the current price (the immediate ceiling for
    runway). None when nothing qualifies — the caller then falls back to a pure
    ``price + k x ATR`` limit rather than a runway-based one (#28). Conservative
    by design: fragile parsing here only ever costs precision, never safety.
    """
    if not analysis_text or not current_price:
        return None
    candidates: list[float] = []
    for m in _UPSIDE_RE.finditer(analysis_text):
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        # Only levels above current price are a ceiling; ignore absurd hits
        # (>3x current is almost certainly a mis-parse, not a near-term target).
        if current_price < val <= current_price * 3:
            candidates.append(val)
    return min(candidates) if candidates else None


def build_guidance(
    ticker: str,
    gain_pct: float,
    price: float | None,
    avg_atr: float | None,
    upside_level: float | None,
    cfg: "TakeProfitConfig",
) -> str:
    """The explicit take-profit directive injected into the advisor prompt (#28).

    Carries the mechanical facts (gain, ATR, a reachable sell-limit, and the ATR
    runway when an upside level is known) and forces the advisor to resolve
    take-profit — bank part of the gain via a whole-share sell-limit, or justify
    holding with concrete remaining upside — rather than staying silent.
    """
    runway = atr_runway(price, upside_level, avg_atr)
    limit = suggest_limit(price, avg_atr, cfg.limit_atr_mult)
    stretch = suggest_limit(price, avg_atr, cfg.stretch_atr_mult)

    lines = [
        "TAKE-PROFIT ZONE ACTIVE (mechanical trigger — ground truth, not an "
        "analyst opinion):",
        f"- This position is a WINNER: unrealized gain is +{gain_pct:.1f}%, which "
        f"has crossed the +{cfg.floor_gain_pct:.0f}% take-profit floor. Do not let "
        "it fully round-trip.",
    ]
    if price is not None:
        lines.append(f"- Current price ${price:.2f}.")
    if avg_atr:
        lines.append(
            f"- ATR (typical daily move) ≈ ${avg_atr:.2f}. A 'good-day-reachable' "
            f"sell-limit is about ${limit:.2f} (price + {cfg.limit_atr_mult:g}xATR); "
            f"a stretch limit if you let it run is about ${stretch:.2f} "
            f"(+ {cfg.stretch_atr_mult:g}xATR)."
        )

    if runway is not None and upside_level is not None:
        lines.append(
            f"- ATR RUNWAY to the cited upside ${upside_level:.2f} is "
            f"{runway:.1f} ATRs of room. Interpret it:"
        )
        if runway < cfg.runway_near_atr:
            lines.append(
                f"    RUNWAY IS SMALL (< {cfg.runway_near_atr:g} ATR) — price is "
                "basically at the ceiling. Bank most or all of the gain now; set "
                "the sell-limit close to the current price."
            )
        elif runway > cfg.runway_far_atr:
            lines.append(
                f"    RUNWAY IS LARGE (> {cfg.runway_far_atr:g} ATR) — there is real "
                "room left. Prefer HOLD, or take only a single share at the higher "
                "stretch limit and let the rest run."
            )
        else:
            lines.append(
                "    RUNWAY IS MODERATE — trim one share into strength; set the "
                "sell-limit around the good-day-reachable level above."
            )
    else:
        lines.append(
            "- No clear upside/resistance level was found in the analysis, so ATR "
            "runway is unknown. Read the analysis for any ceiling; if none, set the "
            "sell-limit around the good-day-reachable level above and lean to "
            "banking at least one share given the gain."
        )

    lines.append(
        "- WHOLE SHARES ONLY: the user does not trade fractional shares. Your "
        "take-profit tranche must be a whole-share count (sell 1 share / 2 shares "
        "/ or the whole position). Respect the ODD-LOT guard: never propose a "
        "fractional sale, and for a tiny whole-share position prefer HOLD or a "
        "full SELL over a trim."
    )
    lines.append(
        "- Fill in the 'Take-Profit:' output line with a concrete sell-limit price "
        "AND the whole-share count to sell there (e.g. 'sell 1 share at 192.50'). "
        "This is a limit ABOVE the current price the user will pre-place to catch "
        "an intraday high. Write N/A only if you are genuinely recommending to hold "
        "the entire position with meaningful upside intact."
    )
    return "\n".join(lines)
