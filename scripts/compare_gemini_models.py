#!/usr/bin/env python
"""Compare the Gemini advisor across MODELS — 3.6 vs 3.5 — WITHOUT re-running the
(expensive) TradingAgents pipeline, and WITHOUT re-billing the 3.6 side (issue #18,
the dropped model bake-off, re-scoped to the one upgrade we actually shipped:
gemini-3.5-flash → gemini-3.6-flash, commit 4bc1e8c).

The advisor only consumes the analysis *result*, so this reconstructs the exact
production prompt from a saved ``~/watchy/reports/*.md`` (ADVISOR_PROMPT +
_format_analysis digest + position/portfolio) and calls ONE new model — the OLD
one (gemini-3.5-flash by default). The 3.6 side is NOT called: the advisor's
output isn't persisted (it only goes to Telegram), so you paste the 3.6 advice you
already received into ``--ref-file`` (or stdin). Net Gemini spend = a single 3.5
call per ticker.

⚠️ Fidelity: the pasted 3.6 text must correspond to the SAME report you compare
against, or the two cells saw different prompts. Pick the report from the same
run that produced the Telegram advice (``--ticker`` picks the newest; override
with ``--report``). The Telegram layout drops the ``Target:`` line (it's consumed
for the #16 derived target, not displayed), so the 3.6 side shows target=N/A.

MANUAL / needs the Gemini api_key in secrets.yaml. Run with the `trading` pyenv.

    # paste the 3.6 Telegram advice into a file first, then:
    python scripts/compare_gemini_models.py --ticker MOD --ref-file /tmp/mod_36.txt
    # or pipe it in:
    python scripts/compare_gemini_models.py --ticker MOD < /tmp/mod_36.txt
    # run the 3.5 cell at a specific thinking level (default: tier2 = low):
    python scripts/compare_gemini_models.py --ticker MOD --ref-file f.txt --level low
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watchy.advisor import (
    ADVISOR_PROMPT,
    _effective_key,
    _format_analysis,
    _gemini_cost_usd,
    _parse_advice,
)
from watchy.config import load_config
from watchy.positions import get_position_source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gemini-model-ab")

_AGENTS = {
    "Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst",
    "Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
    "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager",
}
_DIVIDER_RE = re.compile(r"^##\s+[IVXLC]+\.\s")
_ADVICE_MAX_TOKENS = 4096  # generous so thinking can't truncate the visible answer

# The old model this A/B validates the upgrade against. 3.6 uses thinkingLevel
# and rejects the legacy thinkingBudget; 3.5-flash accepts thinkingLevel too.
_DEFAULT_OLD_MODEL = "gemini-3.5-flash"
# gemini-3.5-flash prices, USD per 1M tokens. Same list price as 3.6-flash as of
# 2026-07 (in $1.50 / out $7.50); update from ai.google.dev/pricing if it drifts.
_OLD_PRICE_IN = 1.50
_OLD_PRICE_OUT = 7.50

_DECISIONS = ("BUY", "SELL", "TRIM", "ADD", "HOLD")


def parse_report(text: str) -> dict[str, str]:
    """Map each ``### <agent>`` section to its body (see compare_gemini_thinking)."""
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


def _thinking_config(level: str) -> dict:
    """Mirror advisor._gemini_thinking_config: "off" → minimal (cheapest tier)."""
    return {"thinkingLevel": "minimal" if level == "off" else level}


def call_gemini(prompt: str, llm, model: str, level: str) -> tuple[str, dict]:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
           f":generateContent?key={_effective_key(llm)}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": _ADVICE_MAX_TOKENS,
            "thinkingConfig": _thinking_config(level),
        },
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    text = ""
    for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        if part.get("text") and not part.get("thought"):
            text = part["text"]
            break
    return text, data.get("usageMetadata", {})


def parse_telegram_advice(raw: str, fallback_ticker: str) -> dict[str, str]:
    """Extract decision/urgency/detail from a pasted Telegram advice message.

    Telegram renders (notify.pipeline_result)::

        Position Advice — $MOD: 🟢 BUY (LOW urgency)
        <detail paragraph...>

    optionally preceded by a "Your Position — $MOD\\n<position>" block. The
    ``Target:`` line is NOT in Telegram (consumed for the #16 derived target), so
    target is left blank. If no "Position Advice" header is found we fall back to
    the raw advisor format (_parse_advice), so a pasted RAW advisor reply also works.
    """
    lines = raw.splitlines()
    hdr_idx = next(
        (i for i, ln in enumerate(lines) if "position advice" in ln.lower()),
        None,
    )
    if hdr_idx is None:
        return _parse_advice(raw.strip(), fallback_ticker)

    header = lines[hdr_idx]
    decision = next((d for d in _DECISIONS if re.search(rf"\b{d}\b", header, re.I)), "")
    m = re.search(r"\(([A-Za-z]+)\s+urgency\)", header, re.I)
    urgency = m.group(1).upper() if m else ""
    detail = "\n".join(lines[hdr_idx + 1:]).strip()
    return {
        "ticker": fallback_ticker,
        "decision": decision.upper(),
        "urgency": urgency,
        "target": "",
        "detail": detail,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticker", default="", help="use the newest report for this ticker")
    ap.add_argument("--report", default="", help="explicit report .md path")
    ap.add_argument("--reports-dir", default="~/watchy/reports")
    ap.add_argument("--ref-file", default="",
                    help="file with the pasted 3.6 Telegram advice (default: read stdin)")
    ap.add_argument("--old-model", default=_DEFAULT_OLD_MODEL,
                    help=f"old model to compare against (default: {_DEFAULT_OLD_MODEL})")
    ap.add_argument("--level", default="low",
                    help="thinking level for the 3.5 call (off/minimal/low/medium/high; "
                         "default low = production Tier 2)")
    args = ap.parse_args()

    # --- resolve the report (same rules as compare_gemini_thinking) ---
    if args.report:
        report_path = Path(os.path.expanduser(args.report))
    else:
        files = sorted(glob.glob(os.path.join(os.path.expanduser(args.reports_dir), "*.md")),
                       key=os.path.getmtime, reverse=True)
        if args.ticker:
            files = [f for f in files if os.path.basename(f).split("_", 1)[0].upper() == args.ticker.upper()]
        if not files:
            print(f"No report found (ticker={args.ticker!r}, dir={args.reports_dir})", file=sys.stderr)
            return 1
        report_path = Path(files[0])

    ticker = report_path.name.split("_", 1)[0]
    sec = parse_report(report_path.read_text(encoding="utf-8"))
    result = result_from_report(sec)
    logger.info("Report: %s  (ticker=%s)", report_path.name, ticker)

    # --- read the pasted 3.6 reference (file or stdin) ---
    if args.ref_file:
        ref_raw = Path(os.path.expanduser(args.ref_file)).read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            print("Paste the 3.6 Telegram advice, then Ctrl-D (Ctrl-Z⏎ on Windows):",
                  file=sys.stderr)
        ref_raw = sys.stdin.read()
    if not ref_raw.strip():
        print("ERROR: no 3.6 reference text (use --ref-file or pipe it via stdin)", file=sys.stderr)
        return 2
    ref = parse_telegram_advice(ref_raw, ticker)

    # --- config / prompt (production-identical) ---
    config = load_config()
    if config.llm.provider != "gemini":
        print(f"advisor provider is {config.llm.provider!r}, not gemini", file=sys.stderr)
        return 2
    llm = config.llm
    ps = get_position_source(config)
    prompt = ADVISOR_PROMPT.format(
        ticker=ticker,
        analysis=_format_analysis(result),
        position=ps.format_position_context(ticker) or "No position held.",
        portfolio=ps.format_portfolio_context() or "Portfolio data unavailable.",
    )

    # --- the ONE new call: the old model ---
    print(f"\n{'='*68}\ncalling {args.old_model}  (thinking level: {args.level})\n{'='*68}")
    try:
        old_text, usage = call_gemini(prompt, llm, args.old_model, args.level)
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    in_tok = int(usage.get("promptTokenCount", 0))
    out_tok = int(usage.get("candidatesTokenCount", 0))
    think_tok = int(usage.get("thoughtsTokenCount", 0))
    usd = (in_tok * _OLD_PRICE_IN + (out_tok + think_tok) * _OLD_PRICE_OUT) / 1_000_000
    old = _parse_advice((old_text or "").strip(), ticker)
    print(f"  in={in_tok} out={out_tok} think={think_tok} usd=${usd:.5f}")

    # --- comparison ---
    new_model = config.llm.model or "gemini-3.6-flash"
    agree = old.get("decision") == ref.get("decision") and bool(ref.get("decision"))
    print(f"\n{'#'*68}\nSUMMARY ({ticker})\n{'#'*68}")
    print(f"{'model':18} {'decision':9} {'urgency':8} {'target':>10}  cost")
    print(f"{new_model:18} {ref.get('decision','?'):9} {ref.get('urgency','?'):8} "
          f"{'N/A (TG)':>10}  $0 (reused)")
    print(f"{args.old_model:18} {old.get('decision','?'):9} {old.get('urgency','?'):8} "
          f"{(old.get('target') or 'N/A'):>10}  ${usd:.5f}")
    print(f"\ndecision match: {'YES' if agree else 'NO'}"
          f"   (3.6={ref.get('decision','?')} vs 3.5={old.get('decision','?')})")

    print(f"\n{'#'*68}\n3.6 ADVICE (reused, from Telegram) — {ticker}\n{'#'*68}")
    print(ref.get("detail") or "(no detail parsed)")
    print(f"\n{'#'*68}\n{args.old_model} ADVICE (fresh) — {ticker}\n{'#'*68}")
    print(old_text or "(empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
