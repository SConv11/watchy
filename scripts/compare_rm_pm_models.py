#!/usr/bin/env python
"""Offline model comparison for the Research Manager & Portfolio Manager (issue #18).

The RM and PM are the only two nodes on the expensive deep-think slot
(``deepseek-v4-pro``). This harness replays them from saved
``~/watchy/reports/*.md`` fixtures on **pro vs flash** — both in thinking mode
(RM/PM always run with thinking on; only the model varies) — to decide
empirically whether the cheaper *flash* model changes the decision.

Why replay from saved reports rather than re-run the whole pipeline: it fixes
the upstream (same analyst reports + debate feed both cells), so any difference
is attributable to the RM/PM model choice, not to run-to-run analyst noise. The
baseline cell (pro) mirrors today's production.

Fidelity caveat: the debate ``history`` fed to each node is reconstructed by
concatenating the per-speaker sections stored in the report (the exact
interleaved transcript isn't saved). This is identical across both cells, so
the *relative* comparison is sound; absolute wording may differ slightly from
the original live run.

MANUAL / needs DEEPSEEK_API_KEY / NOT wired into the daemon.

    DEEPSEEK_API_KEY=... python scripts/compare_rm_pm_models.py \
        --reports-dir ~/watchy/reports --limit 5

Run it with the `trading` pyenv python (the one the daemon uses), so
TradingAgents and langchain are importable.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from glob import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODELS = {"pro": "deepseek-v4-pro", "flash": "deepseek-v4-flash"}
# Cells are just the model tier — RM/PM always run thinking on. Baseline = pro.
CELLS = ["pro", "flash"]
BASELINE = "pro"
RATING_RE = re.compile(
    r"\*\*(?:Recommendation|Rating)\*\*:\s*(Buy|Overweight|Hold|Underweight|Sell)",
    re.IGNORECASE,
)
PRICE_RE = re.compile(r"\$?\d{2,6}(?:\.\d+)?")
# The exact agent sub-headings _save_report writes ("### <name>"). Only these are
# section boundaries — the analyst/researcher bodies contain their OWN #/##/###
# headings (e.g. "## KEY METRICS SUMMARY TABLE", "### Long-Term Trend"), which
# must stay in the body, not fragment it.
_AGENTS = {
    "Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst",
    "Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
    "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager",
}
# Roman-numeral team dividers ("## II. Research Team Decision") — distinct from the
# analysts' own "## 1." / "## KEY METRICS" headings, so they can bound a section.
_DIVIDER_RE = re.compile(r"^##\s+[IVXLC]+\.\s")


@dataclass
class CellResult:
    model_tier: str
    rating: str
    text: str
    latency_s: float
    usd: float
    out_tok: int
    reason_tok: int
    error: str = ""

    @property
    def reason_pct(self) -> float:
        return 100.0 * self.reason_tok / self.out_tok if self.out_tok else 0.0


def parse_report(text: str) -> dict[str, str]:
    """Map each agent section (from _save_report) to its FULL body.

    Only ``### <known agent name>`` lines are treated as boundaries; every other
    heading (the roman ``## I.`` dividers and the analysts' own internal
    ``##``/``###`` headings) stays in the body, so a report is not fragmented.
    """
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


def rm_state(ticker: str, sec: dict[str, str]) -> dict:
    bull = sec.get("Bull Researcher", "")
    bear = sec.get("Bear Researcher", "")
    history = ""
    if bull:
        history += f"Bull Analyst: {bull}\n\n"
    if bear:
        history += f"Bear Analyst: {bear}\n\n"
    return {
        "company_of_interest": ticker,
        "investment_debate_state": {
            "history": history.strip(),
            "bull_history": bull,
            "bear_history": bear,
            "count": 1,
        },
    }


def pm_state(ticker: str, sec: dict[str, str]) -> dict:
    agg = sec.get("Aggressive Analyst", "")
    con = sec.get("Conservative Analyst", "")
    neu = sec.get("Neutral Analyst", "")
    history = ""
    for speaker, txt in [("Risky", agg), ("Safe", con), ("Neutral", neu)]:
        if txt:
            history += f"{speaker} Analyst: {txt}\n\n"
    return {
        "company_of_interest": ticker,
        "risk_debate_state": {
            "history": history.strip(),
            "aggressive_history": agg,
            "conservative_history": con,
            "neutral_history": neu,
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "count": 1,
        },
        "investment_plan": sec.get("Research Manager", ""),
        "trader_investment_plan": sec.get("Trader", ""),
        "past_context": "",
    }


def rating_of(text: str) -> str:
    m = RATING_RE.search(text or "")
    return m.group(1).title() if m else "?"


def faithfulness(text: str, source: str) -> tuple[int, int] | None:
    """(price tokens present in source, total price tokens) — hallucination check."""
    prices = {p.lstrip("$") for p in PRICE_RE.findall(text or "")}
    if not prices:
        return None
    present = sum(1 for p in prices if p in source)
    return present, len(prices)


def run_cell(node_name, state, model_tier, deps):
    """Run one model cell; capture rating, cost, latency. Never raises."""
    TokenCostTracker = deps["TokenCostTracker"]
    DeepSeekChatOpenAI = deps["DeepSeekChatOpenAI"]
    factory = deps["rm"] if node_name == "RM" else deps["pm"]
    out_key = "investment_plan" if node_name == "RM" else "final_trade_decision"

    tracker = TokenCostTracker()
    t0 = time.perf_counter()
    try:
        llm = DeepSeekChatOpenAI(
            model=MODELS[model_tier],
            base_url=DEEPSEEK_BASE_URL,
            api_key=os.environ["DEEPSEEK_API_KEY"],
            callbacks=[tracker],
            max_retries=2,
            timeout=180,
        )
        result = factory(llm)(state)
        text = str(result.get(out_key, ""))
        err = ""
    except Exception as exc:  # noqa: BLE001 - a bad cell must not kill the grid
        text, err = "", f"{type(exc).__name__}: {exc}"
    dt = time.perf_counter() - t0

    bucket = tracker.by_model.get(model_tier)
    return CellResult(
        model_tier=model_tier,
        rating=rating_of(text),
        text=text,
        latency_s=dt,
        usd=tracker.total_usd(),
        out_tok=bucket.output if bucket else 0,
        reason_tok=bucket.reasoning if bucket else 0,
        error=err,
    )


def _load_deps():
    from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
    from tradingagents.agents.managers.research_manager import create_research_manager
    from tradingagents.llm_clients.openai_client import DeepSeekChatOpenAI

    from watchy.token_tracker import TokenCostTracker

    return {
        "rm": create_research_manager,
        "pm": create_portfolio_manager,
        "DeepSeekChatOpenAI": DeepSeekChatOpenAI,
        "TokenCostTracker": TokenCostTracker,
    }


def _fixture_files(reports_dir: str, tickers: set[str] | None, limit: int) -> list[Path]:
    files = [Path(p) for p in glob(os.path.join(os.path.expanduser(reports_dir), "*.md"))]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if tickers:
        files = [f for f in files if f.name.split("_", 1)[0].upper() in tickers]
    return files[:limit]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports-dir", default="~/watchy/reports")
    ap.add_argument("--tickers", default="", help="comma-separated filter, e.g. NVDA,AAPL")
    ap.add_argument("--limit", type=int, default=5, help="most recent N fixtures")
    ap.add_argument("--nodes", default="RM,PM", help="which nodes: RM, PM, or both")
    ap.add_argument("--out", default="", help="dir to dump raw per-cell decision text")
    args = ap.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("ERROR: set DEEPSEEK_API_KEY", file=sys.stderr)
        return 2
    try:
        deps = _load_deps()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR importing TradingAgents/watchy: {exc}\n"
              "Run with the daemon's `trading` pyenv python.", file=sys.stderr)
        return 2

    tickers = {t.strip().upper() for t in args.tickers.split(",") if t.strip()} or None
    nodes = [n.strip().upper() for n in args.nodes.split(",") if n.strip()]
    files = _fixture_files(args.reports_dir, tickers, args.limit)
    if not files:
        print(f"No fixtures under {args.reports_dir}", file=sys.stderr)
        return 1
    out_dir = Path(os.path.expanduser(args.out)) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    agree: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    cost: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for f in files:
        text = f.read_text(encoding="utf-8")
        ticker = f.name.split("_", 1)[0]
        sec = parse_report(text)
        for node in nodes:
            state = rm_state(ticker, sec) if node == "RM" else pm_state(ticker, sec)
            print(f"\n{'='*68}\n{ticker}  [{node}]  ({f.name})\n{'='*68}")
            print(f"{'model':6} {'rating':11} {'lat(s)':>7} {'usd':>9} "
                  f"{'out':>7} {'reason':>7} {'r%':>5}  faithful")
            baseline_rating = None
            for tier in CELLS:
                r = run_cell(node, state, tier, deps)
                if r.error:
                    print(f"{tier:6} ERROR: {r.error}")
                    continue
                if tier == BASELINE:
                    baseline_rating = r.rating
                fth = faithfulness(r.text, text)
                fth_s = f"{fth[0]}/{fth[1]}" if fth else "-"
                print(f"{tier:6} {r.rating:11} {r.latency_s:7.1f} {r.usd:9.5f} "
                      f"{r.out_tok:7d} {r.reason_tok:7d} {r.reason_pct:5.0f}  {fth_s}")
                cost[node][tier].append(r.usd)
                if baseline_rating is not None:
                    agree[node][tier].append(int(r.rating == baseline_rating))
                if out_dir:
                    (out_dir / f"{ticker}_{node}_{tier}.md").write_text(r.text, encoding="utf-8")

    # --- aggregate: flash vs the pro baseline ---
    print(f"\n{'#'*68}\nSUMMARY vs {BASELINE} baseline  (n={len(files)} fixtures)\n{'#'*68}")
    for node in nodes:
        base = cost[node].get(BASELINE)
        base_avg = sum(base) / len(base) if base else 0.0
        print(f"\n[{node}]  baseline ({BASELINE}) avg ${base_avg:.5f}/call")
        print(f"  {'model':6} {'agree%':>7} {'avg usd':>9} {'vs base':>9}")
        for tier in CELLS:
            usds = cost[node].get(tier, [])
            avg = sum(usds) / len(usds) if usds else 0.0
            ag = agree[node].get(tier, [])
            ag_pct = 100.0 * sum(ag) / len(ag) if ag else 0.0
            delta = f"{100*(avg-base_avg)/base_avg:+.0f}%" if base_avg else "-"
            note = "  <- baseline" if tier == BASELINE else ""
            print(f"  {tier:6} {ag_pct:6.0f}% {avg:9.5f} {delta:>9}{note}")
    print(f"\nagree% = final rating matched the {BASELINE} baseline on the same fixture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
