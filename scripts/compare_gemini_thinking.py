#!/usr/bin/env python
"""Compare the Gemini advisor with thinking OFF vs ON — WITHOUT re-running the
(expensive) TradingAgents pipeline (issue #18 / the ③ thinking A/B).

The advisor only consumes the analysis *result*, so this reconstructs that result
from a saved ``~/watchy/reports/*.md`` and calls the real advisor twice
(``gemini_thinking_budget`` 0 vs -1). You get both GEMINICOST lines (cost + think
tokens) and both advice outputs side by side — for the price of 2 Gemini calls,
no DeepSeek pipeline.

MANUAL / needs the Gemini api_key in secrets.yaml. Run with the daemon's `trading`
pyenv python.

    python scripts/compare_gemini_thinking.py --ticker MOD
    python scripts/compare_gemini_thinking.py --report ~/watchy/reports/MOD_....md
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watchy.advisor import get_advice
from watchy.config import load_config
from watchy.positions import get_position_source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gemini-ab")

# Same section granularity as compare_rm_pm_models: only ### <agent> headings and
# roman dividers bound sections; analysts' internal ##/### stay in the body.
_AGENTS = {
    "Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst",
    "Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
    "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager",
}
_DIVIDER_RE = re.compile(r"^##\s+[IVXLC]+\.\s")


def parse_report(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("### ") and stripped[4:].strip() in _AGENTS:
            if current:
                out[current] = "\n".join(buf).strip()
            current = stripped[4:].strip()
            buf = []
        elif _DIVIDER_RE.match(stripped):
            if current:
                out[current] = "\n".join(buf).strip()
            current = None
            buf = []
        elif current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return out


def result_from_report(sec: dict[str, str]) -> dict:
    """Reconstruct the advisor's input dict from a parsed report.

    Mirrors what pipeline_runner puts in the result: the four full analyst
    reports (advisor extracts each one's summary tail), the trader plan, and the
    Portfolio Manager's final decision.
    """
    return {
        "_reports": {
            "market_report": sec.get("Market Analyst", ""),
            "sentiment_report": sec.get("Sentiment Analyst", ""),
            "news_report": sec.get("News Analyst", ""),
            "fundamentals_report": sec.get("Fundamentals Analyst", ""),
        },
        "trader_plan": sec.get("Trader", ""),
        "_decision_raw": sec.get("Portfolio Manager", ""),
        "recommendations": [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticker", default="", help="use the newest report for this ticker")
    ap.add_argument("--report", default="", help="explicit report .md path")
    ap.add_argument("--reports-dir", default="~/watchy/reports")
    args = ap.parse_args()

    if args.report:
        report_path = Path(os.path.expanduser(args.report))
    else:
        pattern = os.path.join(os.path.expanduser(args.reports_dir), "*.md")
        files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if args.ticker:
            files = [f for f in files if os.path.basename(f).split("_", 1)[0].upper() == args.ticker.upper()]
        if not files:
            print(f"No report found (ticker={args.ticker!r}, dir={args.reports_dir})", file=sys.stderr)
            return 1
        report_path = Path(files[0])

    ticker = report_path.name.split("_", 1)[0]
    sec = parse_report(report_path.read_text(encoding="utf-8"))
    result = result_from_report(sec)
    logger.info("Report: %s  (ticker=%s, sections=%s)", report_path.name, ticker, sorted(sec))

    config = load_config()
    if config.llm.provider != "gemini":
        print(f"advisor provider is {config.llm.provider!r}, not gemini — nothing to compare", file=sys.stderr)
        return 2
    position_source = get_position_source(config)

    outputs: dict[int, dict | None] = {}
    for budget in (0, -1):
        label = "OFF" if budget == 0 else "ON (dynamic)"
        print(f"\n{'='*68}\nthinking {label}  (gemini_thinking_budget={budget})\n{'='*68}")
        config.llm.gemini_thinking_budget = budget  # the GEMINICOST line prints think=
        outputs[budget] = get_advice(ticker, result, position_source, config)

    print(f"\n{'#'*68}\nADVICE SIDE BY SIDE ({ticker})\n{'#'*68}")
    for budget in (0, -1):
        adv = outputs[budget] or {}
        print(f"\n--- thinking {'OFF' if budget == 0 else 'ON'} ---")
        print(f"decision={adv.get('decision')!r} urgency={adv.get('urgency')!r} target={adv.get('target')!r}")
        print(adv.get("detail", "(no advice)"))
    print("\nCompare the GEMINICOST lines above for cost/think tokens; judge the "
          "two detail paragraphs for whether thinking improved the advice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
