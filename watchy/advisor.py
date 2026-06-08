"""LLM-based position advisor.

Takes a TradingAgents analysis report + position data (from any PositionSource)
and produces actionable advice on whether to alter the position.

The advisor is a lightweight LLM call — it synthesizes, it doesn't re-analyze.
All the deep analysis is already done by TradingAgents.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from watchy.config import LLMConfig, WatchyConfig
from watchy.positions import PositionSource

logger = logging.getLogger(__name__)

ADVISOR_PROMPT = """You are a portfolio advisor. Below is a full analysis report from a
team of financial analysts (market, sentiment, fundamentals, and risk), plus
the user's current position and portfolio overview.

Consider the user's overall portfolio composition when making your decision.
Avoid over-concentration in any single sector or ticker. If the portfolio is
already heavy in this name or sector, lean toward trimming or holding rather
than adding.

Respond in this exact format:

Ticker: {ticker}
Decision: <BUY / SELL / TRIM / ADD / HOLD>
Urgency: <HIGH / MEDIUM / LOW>

Then write a detailed paragraph (5-8 sentences) covering:
  - Specific entry/exit price target or range, referencing levels from the analysis
  - Suggested position size with rationale (e.g. "3% of portfolio / $5,000")
  - The 2-3 key reasons from the analysis that support this decision
  - The primary risk(s) that could invalidate this recommendation
  - Any conditions the user should watch for (e.g. "if it breaks below X, exit")

Be specific and data-driven — cite actual prices, indicator values, and analyst
findings from the report. Do NOT use JSON, markdown tables, or bullet points.

--- FULL ANALYSIS REPORT ---
Ticker: {ticker}
{analysis}

--- YOUR CURRENT POSITION ---
{position}

--- YOUR PORTFOLIO OVERVIEW ---
{portfolio}
"""


def get_advice(
    ticker: str,
    analysis_result: dict[str, Any],
    position_source: PositionSource,
    config: WatchyConfig,
) -> dict[str, str] | None:
    """Synthesize position-aware advice from analysis + portfolio.

    Returns a dict with keys: ticker, decision, urgency, detail.
    Returns None if no LLM key is configured or the call fails.
    """
    llm = config.llm
    if not _effective_key(llm):
        field = "deepseek_api_key/api_key" if llm.provider == "deepseek" else "api_key"
        logger.info("No LLM %s configured — skipping advisor synthesis", field)
        return None

    position_text = position_source.format_position_context(ticker) or "No position held."
    portfolio_text = position_source.format_portfolio_context() or "Portfolio data unavailable."

    analysis_text = _format_analysis(analysis_result)

    prompt = ADVISOR_PROMPT.format(
        ticker=ticker,
        analysis=analysis_text,
        position=position_text,
        portfolio=portfolio_text,
    )

    try:
        if llm.provider == "anthropic":
            result = _call_anthropic(prompt, llm)
        elif llm.provider in ("openai", "deepseek"):
            result = _call_openai_compatible(prompt, llm)
        elif llm.provider == "gemini":
            result = _call_gemini(prompt, llm)
        else:
            logger.warning("Unknown LLM provider: %s", llm.provider)
            return None

        parsed = _parse_advice(result.strip(), ticker)
        logger.info(
            "Advisor for %s: decision=%s urgency=%s",
            ticker, parsed.get("decision"), parsed.get("urgency"),
        )
        return parsed
    except Exception:
        logger.exception("Advisor synthesis failed for %s", ticker)
        return None


def _parse_advice(raw: str, fallback_ticker: str) -> dict[str, str]:
    """Parse the structured advice output into a dict.

    Expected format::

        Ticker: NVDA
        Decision: BUY
        Urgency: HIGH

        <detail paragraph...>
    """
    parsed: dict[str, str] = {
        "ticker": fallback_ticker,
        "decision": "",
        "urgency": "",
        "detail": "",
    }

    # Scan every line for the header fields (first match wins) rather than
    # stopping at the first non-header line — the model sometimes emits a blank
    # line or a short preamble before "Decision:", which previously dropped the
    # decision/urgency entirely. Non-header lines become the detail paragraph.
    got = {"ticker": False, "decision": False, "urgency": False}
    detail_lines: list[str] = []
    for line in raw.split("\n"):
        stripped = line.strip()
        low = stripped.lower()
        if not got["ticker"] and low.startswith("ticker:"):
            val = stripped.split(":", 1)[1].strip()
            if val:
                parsed["ticker"] = val
            got["ticker"] = True
        elif not got["decision"] and low.startswith("decision:"):
            parsed["decision"] = stripped.split(":", 1)[1].strip().upper()
            got["decision"] = True
        elif not got["urgency"] and low.startswith("urgency:"):
            parsed["urgency"] = stripped.split(":", 1)[1].strip().upper()
            got["urgency"] = True
        elif stripped:
            detail_lines.append(stripped)

    parsed["detail"] = " ".join(detail_lines)
    return parsed


def _format_analysis(result: dict[str, Any]) -> str:
    """Build a rich analysis summary for the advisor LLM.

    Uses the full untruncated analyst reports when available (from
    ``_reports``), falling back to the truncated summary fields.
    """
    parts: list[str] = []

    # Full analyst reports (preferred — no truncation)
    reports = result.get("_reports", {})
    for key, label in [
        ("market_report", "Market Analyst"),
        ("sentiment_report", "Sentiment Analyst"),
        ("news_report", "News Analyst"),
        ("fundamentals_report", "Fundamentals Analyst"),
    ]:
        text = reports.get(key) or ""
        if text:
            parts.append(f"--- {label} ---\n{text}")

    # If no full reports, fall back to recommendations field
    if not parts:
        recs = result.get("recommendations", [])
        if recs:
            parts.append("Recommendations:\n" + "\n".join(recs))

    # Risk assessment
    risk = result.get("risk_assessment")
    if risk:
        parts.append(f"--- Risk Assessment ---\n{risk}")

    # Trader plan + final decision (untruncated from _decision_raw)
    decision = result.get("_decision_raw") or ""
    if decision:
        parts.append(f"--- Final Decision ---\n{decision}")

    # SEPA stage context
    stage = result.get("stage_context", {})
    if stage:
        sepa = stage.get("sepa_stage")
        if sepa:
            names = {1: "Basing", 2: "Advancing", 3: "Topping", 4: "Declining"}
            parts.append(f"SEPA Stage: {names.get(sepa, '?')} (stage {sepa})")

    if not parts:
        return json.dumps(result)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM API call helpers
# ---------------------------------------------------------------------------


# Advice is a structured header + a 5-8 sentence paragraph with price targets,
# sizing, reasons, risks. 600 tokens truncated it mid-sentence (and on Gemini 2.5
# thinking models the budget is shared with hidden reasoning), so give it room.
_ADVICE_MAX_TOKENS = 1024


def _effective_key(llm: LLMConfig) -> str:
    """Resolve the API key for the configured provider.

    DeepSeek keys live in `deepseek_api_key` (so an Anthropic/OpenAI key can
    coexist in `api_key`); fall back to `api_key` if that field is empty.
    """
    if llm.provider == "deepseek":
        return llm.deepseek_api_key or llm.api_key
    return llm.api_key


def _call_anthropic(prompt: str, llm: LLMConfig) -> str:
    """Call Anthropic Messages API for advice synthesis."""
    import urllib.request

    url = llm.api_base or "https://api.anthropic.com/v1/messages"
    if not url.endswith("/messages"):
        url = url.rstrip("/") + "/messages"

    body = json.dumps({
        "model": llm.model,
        "max_tokens": _ADVICE_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": _effective_key(llm),
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        return data["content"][0]["text"]


def _call_openai_compatible(prompt: str, llm: LLMConfig) -> str:
    """Call OpenAI-compatible Chat API (OpenAI, DeepSeek, etc.)."""
    import urllib.request

    default_bases = {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
    }
    base = llm.api_base or default_bases.get(llm.provider, "https://api.openai.com/v1")
    url = base.rstrip("/") + "/chat/completions"

    body = json.dumps({
        "model": llm.model,
        "max_tokens": _ADVICE_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_effective_key(llm)}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, llm: LLMConfig) -> str:
    """Call Google Gemini API for advice synthesis.

    Uses the Gemini REST API (not Vertex AI).
    API key from: https://aistudio.google.com/apikey
    """
    import urllib.request

    model = llm.model or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={_effective_key(llm)}"

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": _ADVICE_MAX_TOKENS,
            # gemini-2.5-flash counts hidden "thinking" tokens against the output
            # budget; disable it so the whole budget produces the visible answer
            # (this is a synthesis task, not one that needs extended reasoning).
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"]
