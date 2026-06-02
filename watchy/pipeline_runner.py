"""TradingAgents bridge — maps Watchy PipelineSpec to TradingAgentsGraph calls.

This is the real pipeline runner that replaces the stub in orchestrator.py.
Each signal type gets the appropriate subset of analysts, debate rounds, and
risk management depth as defined in the graduated analysis matrix.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from watchy.orchestrator import AnalystSet, DebateMode, PipelineSpec, RiskMode

logger = logging.getLogger(__name__)

# Default report output directory (overridable via extra_config).
DEFAULT_REPORTS_DIR = os.path.expanduser("~/watchy/reports")


def create_tradingagents_runner(
    *,
    llm_provider: str = "deepseek",
    deep_think_llm: str = "deepseek-v4-pro",
    quick_think_llm: str = "deepseek-v4-flash",
    backend_url: str | None = None,
    **extra_config: Any,
):
    """Factory that returns a ``PipelineRunner`` wired to real TradingAgents.

    Args:
        llm_provider: One of openai, google, anthropic, deepseek, etc.
        deep_think_llm: Model for complex reasoning (Research Manager, PM).
        quick_think_llm: Model for analysts, debaters, and trader.
        backend_url: Optional custom API endpoint.
        **extra_config: Passed through to the TradingAgents config dict
            (e.g. max_debate_rounds, data_cache_dir, ...).

    Returns:
        A callable suitable for ``PipelineRunner``.
    """

    # Defer import so the module is importable even without TradingAgents
    # installed (e.g. during linting or unit tests on a different machine).
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    def runner(ticker: str, spec: PipelineSpec) -> dict[str, Any]:
        """Execute the TradingAgents pipeline for *ticker* per *spec*.

        Creates a fresh graph instance per call. This is intentional: each
        signal type gets a different analyst subset and debate/risk depth.
        Watchy fires at most a handful of signals per hour so the compile
        overhead (~200 ms) is negligible.
        """
        # ---- 1. Map PipelineSpec → TradingAgents config ------------------
        selected_analysts = _map_analysts(spec.analysts)
        if not selected_analysts:
            logger.info("No analysts selected for %s — skipping TA call", ticker)
            return {
                "ticker": ticker,
                "analysts_run": [],
                "debate": spec.debate.value,
                "risk_mode": spec.risk.value,
                "recommendations": [],
                "risk_assessment": None,
                "summary": f"[SKIP] No analysts requested for {ticker}.",
            }

        config = DEFAULT_CONFIG.copy()
        config["llm_provider"] = llm_provider
        config["deep_think_llm"] = deep_think_llm
        config["quick_think_llm"] = quick_think_llm
        if backend_url:
            config["backend_url"] = backend_url
        config["max_debate_rounds"] = _map_debate(spec.debate)
        config["max_risk_discuss_rounds"] = _map_risk(spec.risk)
        config.update(extra_config)

        # ---- 2. Run the graph -------------------------------------------
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        logger.info(
            "Launching TA graph for %s: analysts=%s debate_rounds=%d risk_rounds=%d",
            ticker,
            selected_analysts,
            config["max_debate_rounds"],
            config["max_risk_discuss_rounds"],
        )

        ta = TradingAgentsGraph(
            selected_analysts=selected_analysts,
            debug=False,
            config=config,
        )

        final_state, decision = ta.propagate(ticker, today)

        # ---- 3. Save reports as markdown --------------------------------
        report_path = _save_report(final_state, ticker, config)

        # ---- 4. Format result for Watchy consumers ----------------------
        result = _format_result(ticker, spec, selected_analysts, final_state, decision)
        if report_path:
            result["report_path"] = str(report_path)
        return result

    return runner


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

# TradingAgents uses "social" as the wire key for Sentiment analyst
# (legacy naming — the method is create_sentiment_analyst but the key
# and tool node are "social").
_ANALYST_MAP: dict[AnalystSet, list[str]] = {
    AnalystSet.NONE: [],
    AnalystSet.MARKET_ONLY: ["market"],
    AnalystSet.MARKET_SENTIMENT: ["market", "social"],
    AnalystSet.MARKET_SENTIMENT_NEWS: ["market", "social", "news"],
    AnalystSet.FULL: ["market", "social", "news", "fundamentals"],
}

# Human-readable names (Watchy-facing, matches orchestrator._analyst_names).
_ANALYST_LABELS: dict[str, str] = {
    "market": "market",
    "social": "sentiment",
    "news": "news",
    "fundamentals": "fundamentals",
}


def _map_analysts(analyst_set: AnalystSet) -> list[str]:
    return _ANALYST_MAP.get(analyst_set, ["market", "social"])


def _map_debate(debate: DebateMode) -> int:
    """Map debate mode to max_debate_rounds.

    0 rounds means the conditional logic immediately exits to Research
    Manager after the first Bull Researcher response — no back-and-forth.
    """
    return 1 if debate == DebateMode.BULL_BEAR else 0


def _map_risk(risk: RiskMode) -> int:
    """Map risk mode to max_risk_discuss_rounds.

    0 rounds skips the 3-way Aggressive/Conservative/Neutral debate;
    the Portfolio Manager still evaluates the trader proposal directly.
    """
    if risk == RiskMode.FULL:
        return 1
    return 0  # NONE or SIMPLIFIED


# ---------------------------------------------------------------------------
# Report saving (markdown, same layout as TradingAgents CLI)
# ---------------------------------------------------------------------------


def _save_report(
    final_state: dict[str, Any],
    ticker: str,
    config: dict[str, Any],
) -> Path | None:
    """Save a single consolidated analysis report as markdown.

    File name format: ``{ticker}_{datetime}.md``
    Saved to ``<reports_dir>/`` (default: ``~/watchy/reports/``).
    """
    reports_dir = config.get("reports_dir", DEFAULT_REPORTS_DIR)
    out_dir = Path(reports_dir)

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Cannot create report dir %s: %s", out_dir, exc)
        return None

    sections: list[str] = []

    # --- 1. Analysts ---
    analyst_parts: list[tuple[str, str]] = []
    for key, name in [
        ("market_report", "Market Analyst"),
        ("sentiment_report", "Sentiment Analyst"),
        ("news_report", "News Analyst"),
        ("fundamentals_report", "Fundamentals Analyst"),
    ]:
        text = final_state.get(key)
        if text:
            analyst_parts.append((name, str(text)))
    if analyst_parts:
        sections.append(
            "## I. Analyst Team Reports\n\n"
            + "\n\n".join(f"### {n}\n{t}" for n, t in analyst_parts)
        )

    # --- 2. Research (Bull/Bear debate) ---
    debate = final_state.get("investment_debate_state", {})
    if debate:
        research_parts: list[tuple[str, str]] = []
        for key, name in [
            ("bull_history", "Bull Researcher"),
            ("bear_history", "Bear Researcher"),
            ("judge_decision", "Research Manager"),
        ]:
            text = debate.get(key)
            if text:
                research_parts.append((name, str(text)))
        if research_parts:
            sections.append(
                "## II. Research Team Decision\n\n"
                + "\n\n".join(f"### {n}\n{t}" for n, t in research_parts)
            )

    # --- 3. Trading ---
    trader_plan = final_state.get("trader_investment_plan")
    if trader_plan:
        sections.append(
            f"## III. Trading Team Plan\n\n### Trader\n{trader_plan}"
        )

    # --- 4. Risk Management ---
    risk = final_state.get("risk_debate_state", {})
    if risk:
        risk_parts: list[tuple[str, str]] = []
        for key, name in [
            ("aggressive_history", "Aggressive Analyst"),
            ("conservative_history", "Conservative Analyst"),
            ("neutral_history", "Neutral Analyst"),
        ]:
            text = risk.get(key)
            if text:
                risk_parts.append((name, str(text)))
        if risk_parts:
            sections.append(
                "## IV. Risk Management Team Decision\n\n"
                + "\n\n".join(f"### {n}\n{t}" for n, t in risk_parts)
            )

        # --- 5. Portfolio Manager ---
        judge = risk.get("judge_decision")
        if judge:
            sections.append(
                f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{judge}"
            )

    # --- Consolidated report ---
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    filename = f"{ticker}_{timestamp}.md"
    report_path = out_dir / filename

    header = (
        f"# Trading Analysis Report: {ticker}\n\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
    )
    report_path.write_text(header + "\n\n".join(sections), encoding="utf-8")

    logger.info("Report saved: %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------


def _format_result(
    ticker: str,
    spec: PipelineSpec,
    selected_analysts: list[str],
    final_state: dict[str, Any],
    decision: Any,
) -> dict[str, Any]:
    """Extract the parts Watchy cares about from the TA graph output."""

    reports: dict[str, str | None] = {
        "market_report": final_state.get("market_report"),
        "sentiment_report": final_state.get("sentiment_report"),
        "news_report": final_state.get("news_report"),
        "fundamentals_report": final_state.get("fundamentals_report"),
    }

    # Collect non-empty analyst reports as recommendations.
    recommendations: list[str] = []
    for key, label in [
        ("market_report", "Market"),
        ("sentiment_report", "Sentiment"),
        ("news_report", "News"),
        ("fundamentals_report", "Fundamentals"),
    ]:
        content = reports.get(key)
        if content:
            # Truncate very long reports for the summary.
            short = content if len(content) <= 300 else content[:297] + "..."
            recommendations.append(f"[{label}] {short}")

    # Extract final decision text.
    decision_text = ""
    if isinstance(decision, dict):
        decision_text = decision.get("decision", decision.get("summary", str(decision)))
    elif isinstance(decision, str):
        decision_text = decision

    # Extract risk assessment from risk debate state.
    risk_assessment = None
    risk_state = final_state.get("risk_debate_state", {})
    if risk_state:
        judge = risk_state.get("judge_decision", "")
        if judge:
            risk_assessment = str(judge)[:500]

    # Summary: combine trader plan + final decision.
    trader_plan = final_state.get("trader_investment_plan", "")
    final_decision = final_state.get("final_trade_decision", "")
    summary_parts = []
    if trader_plan:
        summary_parts.append(str(trader_plan)[:400])
    if final_decision:
        summary_parts.append(f"Decision: {final_decision}")
    if decision_text:
        summary_parts.append(str(decision_text)[:300])

    analysts_run = [_ANALYST_LABELS.get(a, a) for a in selected_analysts]

    return {
        "ticker": ticker,
        "analysts_run": analysts_run,
        "debate": spec.debate.value,
        "risk_mode": spec.risk.value,
        "recommendations": recommendations,
        "risk_assessment": risk_assessment,
        "summary": "\n\n".join(summary_parts) if summary_parts else "Analysis complete.",
        # Full reports for downstream consumers (advisor, notifications).
        "_reports": reports,
        "_decision_raw": decision_text,
    }
