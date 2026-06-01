"""LLM-based position advisor.

Takes a TradingAgents analysis report + Schwab position data and produces
actionable advice on whether to alter the position.

The advisor is a lightweight LLM call — it synthesizes, it doesn't re-analyze.
All the deep analysis is already done by TradingAgents.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from watchy.config import LLMConfig, WatchyConfig
from watchy.schwab import SchwabClient

logger = logging.getLogger(__name__)

ADVISOR_PROMPT = """You are a portfolio advisor. Given an analysis report from a team of
financial analysts and the user's current position, provide a clear, specific
recommendation on whether the user should alter their position.

Respond with a JSON object with these fields:
  - action: one of "buy", "sell", "trim", "add", "hold"
  - reasoning: 2-4 sentences explaining why, referencing specific points from the analysis
  - urgency: "high", "medium", or "low"
  - suggested_size: optional, a suggestion like "2% of portfolio" or "10 shares"
  - risk_note: one sentence about the primary risk to this recommendation

--- ANALYSIS REPORT ---
Ticker: {ticker}
{analysis}

--- CURRENT POSITION ---
{position}

--- PORTFOLIO CONTEXT ---
{portfolio}
"""


def get_advice(
    ticker: str,
    analysis_result: dict[str, Any],
    schwab: SchwabClient,
    config: WatchyConfig,
) -> dict[str, Any] | None:
    """Synthesize position-aware advice from analysis + portfolio state.

    Returns a dict with keys: action, reasoning, urgency, suggested_size,
    risk_note. Returns None if LLM is not configured or the call fails.
    """
    llm = config.llm
    if not llm.api_key:
        logger.info("No LLM API key configured — skipping advisor synthesis")
        return None

    position_text = schwab.format_position_context(ticker) or "No position held."
    portfolio_text = schwab.format_portfolio_context() or "Portfolio data unavailable."

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

        advice = json.loads(result)
        logger.info("Advisor for %s: action=%s urgency=%s", ticker, advice.get("action"), advice.get("urgency"))
        return advice
    except Exception:
        logger.exception("Advisor synthesis failed for %s", ticker)
        return None


def _format_analysis(result: dict[str, Any]) -> str:
    parts = []

    recs = result.get("recommendations", [])
    if recs:
        parts.append("Recommendations: " + "; ".join(recs))

    risk = result.get("risk_assessment")
    if risk:
        parts.append(f"Risk assessment: {risk}")

    summary = result.get("summary", "")
    if summary:
        parts.append(f"Summary: {summary}")

    analysts = result.get("analysts_run", [])
    if analysts:
        parts.append(f"Analysts consulted: {', '.join(analysts)}")

    stage = result.get("stage_context", {})
    if stage:
        sepa = stage.get("sepa_stage")
        if sepa:
            names = {1: "Basing", 2: "Advancing", 3: "Topping", 4: "Declining"}
            parts.append(f"SEPA stage: {names.get(sepa, '?')} (stage {sepa})")

    return "\n".join(parts) if parts else json.dumps(result)


def _call_anthropic(prompt: str, llm: LLMConfig) -> str:
    """Call Anthropic Messages API for advice synthesis."""
    import urllib.request

    url = llm.api_base or "https://api.anthropic.com/v1/messages"
    if not url.endswith("/messages"):
        url = url.rstrip("/") + "/messages"

    body = json.dumps({
        "model": llm.model,
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": llm.api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        return data["content"][0]["text"]


def _call_openai_compatible(prompt: str, llm: LLMConfig) -> str:
    """Call OpenAI-compatible Chat API (OpenAI, DeepSeek, and other compatible providers).

    DeepSeek: set provider=deepseek, model=deepseek-chat (or deepseek-reasoner).
    The api_base defaults to https://api.deepseek.com/v1 for provider=deepseek.
    """
    import urllib.request

    default_bases = {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
    }
    base = llm.api_base or default_bases.get(llm.provider, "https://api.openai.com/v1")
    url = base.rstrip("/") + "/chat/completions"

    body = json.dumps({
        "model": llm.model,
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm.api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, llm: LLMConfig) -> str:
    """Call Google Gemini API for advice synthesis.

    Set provider=gemini, model=gemini-2.5-flash (or gemini-2.5-pro).
    Uses the Gemini REST API (not Vertex AI).
    API key from: https://aistudio.google.com/apikey
    """
    import urllib.request

    model = llm.model or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={llm.api_key}"

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 400},
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        # Gemini response: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
        return data["candidates"][0]["content"]["parts"][0]["text"]
