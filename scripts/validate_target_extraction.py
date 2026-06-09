"""Validate the #16 auto-target extraction end-to-end against the real LLM.

The Tier 2 proximity gate (#15) self-maintains its target from the advisor's
`Target:` field (#16). Unit tests cover the parsing, but NOT whether the live
LLM actually emits a parseable `Target:` line — that's the one link only a real
call can verify. This script isolates that link: it feeds a canned, realistic
analysis (no expensive TradingAgents pipeline) to the real advisor and checks
that a numeric target comes back.

Run on the VPS with the trading-env python (needs ~/watchy_config/secrets.yaml):

    /home/watchy/.pyenv/versions/3.11.9/envs/trading/bin/python \
        scripts/validate_target_extraction.py

Exit code 0 = OK (target parsed), 1 = FAIL (no/unparseable target or no LLM).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from watchy.advisor import get_advice, parse_price
from watchy.config import load_config
from watchy.positions import get_position_source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("validate_target")

TICKER = "AMZN"

# A canned analysis result shaped exactly like pipeline_runner._format_result
# output (the keys get_advice reads): full reports, risk assessment, decision.
# It deliberately states concrete price levels so a faithful advisor should be
# able to distill a Target.
_CANNED_RESULT = {
    "ticker": TICKER,
    "analyst_count": 2,
    "verdict": "BUY",
    "_reports": {
        "market_report": (
            "AMZN closed at $246.10, having breached the lower Bollinger Band "
            "($248). The 50-day SMA sits at $258 and the 200-day at $231. RSI is "
            "38 (approaching oversold). Key support is the $230-232 zone; the next "
            "resistance is the 50-day at $258, then the prior swing high near $274."
        ),
        "sentiment_report": (
            "Sentiment is net bullish on the Amazon-Corning fiber deal and the AI "
            "capex cycle, tempered by near-term momentum weakness vs QQQ."
        ),
        "news_report": None,
        "fundamentals_report": None,
    },
    "risk_assessment": (
        "Rating: Overweight. Initiate a half-size position near $246 with a hard "
        "stop at $229.50; targets $274 / $300 / $317. Reserve the second half for "
        "a confirmed bounce off $230-232 or a volume reclaim of the 50-day SMA."
    ),
    "_decision_raw": (
        "FINAL TRANSACTION PROPOSAL: **BUY**. Accumulate on weakness into the "
        "$230-246 entry zone; the long-term AWS/AI thesis outweighs near-term drift."
    ),
    "stage_context": {"sepa_stage": 2},
}


def main() -> int:
    try:
        config = load_config()
    except FileNotFoundError:
        logger.error("Config not found — copy config.yaml + secrets.yaml to ~/watchy_config/")
        return 1

    logger.info("LLM provider=%s model=%s", config.llm.provider, config.llm.model)

    position_source = get_position_source(config)

    logger.info("Calling the real advisor for %s (canned analysis)...", TICKER)
    advice = get_advice(TICKER, _CANNED_RESULT, position_source, config)

    if not advice:
        logger.error("FAIL — advisor returned no advice (no LLM key, or API error). "
                     "Target cannot be derived; the gate would never skip this ticker.")
        return 1

    raw_target = advice.get("target", "")
    decision = advice.get("decision", "?")
    urgency = advice.get("urgency", "?")
    logger.info("Advisor returned: decision=%s urgency=%s target=%r",
                decision, urgency, raw_target)

    parsed = parse_price(raw_target)
    if parsed is None:
        logger.error(
            "FAIL — advisor produced no parseable Target (got %r). The #16 "
            "auto-target would stay empty and the #15 weekday gate would never "
            "skip (safe, but the cost-saving doesn't kick in). If this persists, "
            "tighten the Target: instruction in ADVISOR_PROMPT.",
            raw_target,
        )
        return 1

    logger.info("OK — Target extracted and parsed: %r -> %.2f", raw_target, parsed)
    logger.info("This is what Tier 2 would persist as derived_target_price for %s.", TICKER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
