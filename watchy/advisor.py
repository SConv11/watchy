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

ADVISOR_PROMPT = """You are a portfolio advisor. Below is a condensed analysis summary
from a team of financial analysts (market, sentiment, fundamentals, and risk) —
the final decision, risk assessment, trader plan, and each analyst's summary
table — plus the user's current position and portfolio overview.

Consider the user's overall portfolio composition when making your decision.
Avoid over-concentration in any single sector or ticker. If the portfolio is
already heavy in this name or sector, lean toward trimming or holding rather
than adding.

CRITICAL — concentration math: judge a position's weight against the TOTAL
ACCOUNT VALUE (equities PLUS cash and cash-equivalents like money-market/sweep),
never against the stock-only total. Use the "Total value" figure in the portfolio
overview as the denominator (it already includes cash); do NOT recompute weight
by summing only the stock positions. Uninvested cash is a risk buffer — a
position that looks heavy versus equities alone can be perfectly healthy versus
the full account (e.g. a $420 holding is 24% of $1,700 in stocks but only 12.6%
of a $3,340 account that also holds $1,700 cash). Do not advise a TRIM for
"over-concentration" unless the weight is high against the full account value.
NEVER add "buying power" or any margin/purchasing-power figure to the account
value to compute net worth or a concentration denominator — buying power is a
leveraged purchasing limit, not money you own. The "Total value" figure is the
sole denominator; it already includes cash and equivalents.

ODD-LOT / TINY-POSITION GUARD: TRIM means selling PART of a holding, so it only
makes sense when the REMAINING position is still a sensible size. If the
position is ALREADY fractional (a non-whole share count), trimming it
fractionally is fine — no new odd lot is created. But when it is not a sensible
size but a whole share, do not force a fractional-share sale. For such tiny
positions choose HOLD, or SELL to exit the entire share when the thesis is
genuinely bearish — never TRIM. The ONE exception: a single high-priced share
(roughly ≥ $1,000 per share) may be trimmed fractionally when the analysis
strongly warrants taking money off the table.

TAKE-PROFIT / DON'T ROUND-TRIP A WINNER: protecting an existing gain matters as
much as finding an entry. When the position already carries a MEANINGFUL
unrealized gain (see "Unrealized P&L" in the position block — as a rough,
NON-binding anchor, think roughly 15%+; a smaller gain rarely qualifies) AND the
analysis shows the move is getting extended — price is at or into the resistance
/ upside-target zone the analysts cite, momentum or volume is waning (weakening
MACD, overbought or rolling-over RSI, a low-volume bounce), or the remaining
upside to the analysts' target is small versus the downside to their stop — lean
toward TRIM to bank part of the gain rather than letting it fully round-trip.
This is deliberately NOT a fixed "up X% -> sell" rule: a strong, still-intact
uptrend with real upside left should be allowed to run (HOLD), and a small gain
with the thesis still early is not a take-profit signal. The trigger is the
COMBINATION of a worthwhile gain and a stalling / extended setup. Respect the
guards above — never force a fractional trim on a tiny whole-share position
(follow the ODD-LOT guard), and judge any resulting weight against full account
value.

Respond in this exact format:

Ticker: {ticker}
Decision: <BUY / SELL / TRIM / ADD / HOLD>
Urgency: <HIGH / MEDIUM / LOW>
Target: <the entry / accumulation price level — where one would BUY or ADD to a
position — as a number like 215.50 (a range like 215-230 is fine). This is NOT a
stop-loss and NOT a take-profit; it's the level to watch for getting in. Write
N/A if the analysis gives no actionable entry level.>

Then write a detailed paragraph (5-8 sentences) covering:
  - Specific entry/exit price target or range, referencing levels from the analysis
  - Suggested position size with rationale (e.g. "3% of portfolio / $5,000").
    Fractional shares are available, but only fall back to them when a single
    whole share is too large for the suggested allocation (i.e. one share costs
    more than the dollar amount you'd allocate); otherwise size in whole shares.
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
    thinking_level: str = "off",
) -> dict[str, str] | None:
    """Synthesize position-aware advice from analysis + portfolio.

    ``thinking_level`` (gemini only): off / minimal / low / medium / high. The
    caller passes the per-tier level (Tier 1 = cheap, Tier 2 = low); ignored by
    the non-gemini providers.

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
            result = _call_gemini(prompt, llm, ticker, thinking_level)
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
        "target": "",
        "detail": "",
    }

    # Scan every line for the header fields (first match wins) rather than
    # stopping at the first non-header line — the model sometimes emits a blank
    # line or a short preamble before "Decision:", which previously dropped the
    # decision/urgency entirely. Non-header lines become the detail paragraph.
    got = {"ticker": False, "decision": False, "urgency": False, "target": False}
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
        elif not got["target"] and low.startswith("target:"):
            # Captured as a header so it doesn't pollute the detail paragraph;
            # the numeric value (for #16's auto-target) is parsed via parse_price.
            parsed["target"] = stripped.split(":", 1)[1].strip()
            got["target"] = True
        elif stripped:
            detail_lines.append(stripped)

    parsed["detail"] = " ".join(detail_lines)
    return parsed


def parse_price(text: str | None) -> float | None:
    """Extract a numeric price from an advisor ``Target:`` value.

    Handles ``$215.50``, ``215.50``, ``215-230`` (→ midpoint), ``$3,000`` and
    returns None for ``N/A`` / empty / no-number strings. A range averages the
    first two numbers; a single value is returned as-is.
    """
    import re

    if not text:
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not nums:
        return None
    vals = [float(n) for n in nums[:2]]
    return sum(vals) / len(vals)


def _analyst_summary_tail(text: str) -> str | None:
    """Extract an analyst's summary tail: its final Markdown table plus the
    conclusion that follows it (transaction proposal / final assessment / etc.),
    to the end of the report.

    Every analyst prompt instructs "append a Markdown table at the end … to
    organize key points"; the table is preceded by the long analytical prose
    (the token-heavy bulk we drop) and followed by a short actionable conclusion
    (kept — it carries the analyst's crisp "why"). Anchors on the LAST contiguous
    run of >=2 ``|``-rows and returns from there to the end. None if no table.
    """
    lines = text.splitlines()
    n = len(lines)
    last_table_start = None
    i = 0
    while i < n:
        if "|" in lines[i] and lines[i].strip():
            j = i
            while j < n and "|" in lines[j] and lines[j].strip():
                j += 1
            if j - i >= 2:  # header + separator at minimum
                last_table_start = i
            i = j
        else:
            i += 1
    if last_table_start is None:
        return None
    return "\n".join(lines[last_table_start:]).strip()


def _format_analysis(result: dict[str, Any]) -> str:
    """Build a compact analysis digest for the advisor LLM.

    Deliberately omits the full analyst prose — the dominant advisor input-token
    cost. The advisor synthesises an already-made decision, so it receives:

      - the decision chain (final decision + risk assessment + trader plan),
        which carries the rating and the concrete entry / stop / target levels;
      - each analyst's summary tail — its final table plus the conclusion that
        follows it — not the long analytical prose that precedes the table;
      - the SEPA stage.

    A report with no summary table falls back to its opening lines; with no
    decision or reports at all, falls back to the truncated recommendations.
    """
    parts: list[str] = []

    # Decision chain — the rating and the concrete price levels live here.
    decision = result.get("_decision_raw") or ""
    if decision:
        parts.append(f"--- Final Decision ---\n{decision}")
    risk = result.get("risk_assessment")
    if risk:
        parts.append(f"--- Risk Assessment ---\n{risk}")
    trader = result.get("trader_plan")
    if trader:
        parts.append(f"--- Trader Plan ---\n{trader}")

    # Analyst signal: each report's trailing summary table, not the full prose.
    reports = result.get("_reports", {})
    for key, label in [
        ("market_report", "Market Analyst"),
        ("sentiment_report", "Sentiment Analyst"),
        ("news_report", "News Analyst"),
        ("fundamentals_report", "Fundamentals Analyst"),
    ]:
        text = reports.get(key) or ""
        if not text:
            continue
        tail = _analyst_summary_tail(text)
        snippet = tail if tail else (text.strip()[:400] + " …")
        parts.append(f"--- {label} (summary) ---\n{snippet}")

    # Fallback: no decision and no reports → truncated recommendations field.
    if not parts:
        recs = result.get("recommendations", [])
        if recs:
            parts.append("Recommendations:\n" + "\n".join(recs))

    # SEPA stage context.
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
# Extra output headroom for the answer when Gemini thinking is enabled — thinking
# tokens share maxOutputTokens, so the visible answer needs its own room on top.
_GEMINI_THINK_HEADROOM = 2048

# gemini-3.5-flash prices, USD per 1M tokens (update from ai.google.dev/pricing).
# Thinking tokens are billed at the output rate. Used only for the greppable
# GEMINICOST log estimate — the token counts logged are exact.
_GEMINI_PRICE_IN = 1.50
_GEMINI_PRICE_OUT = 7.50


def _gemini_cost_usd(in_tok: int, out_tok: int, think_tok: int) -> float:
    """Approximate USD for one Gemini call (thinking billed as output)."""
    return (in_tok * _GEMINI_PRICE_IN + (out_tok + think_tok) * _GEMINI_PRICE_OUT) / 1_000_000


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


def _gemini_thinking_config(level: str) -> dict:
    """Map a thinking level to the gemini-3.x generateContent thinkingConfig.

    gemini-3.6-flash uses ``thinkingLevel`` (minimal/low/medium/high; default
    medium) and REJECTS the legacy ``thinkingBudget`` with HTTP 400 (verified on
    3.6, 2026-07-21). Thinking can't be fully switched off, so "off" maps to the
    cheapest tier, ``minimal`` — which in practice still emits ~0 thinking tokens.
    """
    return {"thinkingLevel": "minimal" if level == "off" else level}


def _call_gemini(prompt: str, llm: LLMConfig, ticker: str = "", level: str = "off") -> str:
    """Call Google Gemini API for advice synthesis.

    Uses the Gemini REST API (not Vertex AI).
    API key from: https://aistudio.google.com/apikey
    """
    import urllib.request

    model = llm.model or "gemini-3.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={_effective_key(llm)}"

    # Thinking tokens share the output budget. On 3.6 every level (including "off"
    # → minimal) can emit thoughts, so always give the visible answer its own
    # headroom. maxOutputTokens is a ceiling, not a charge, so this is free.
    max_out = _ADVICE_MAX_TOKENS + _GEMINI_THINK_HEADROOM
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_out,
            "thinkingConfig": _gemini_thinking_config(level),
        },
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    # Greppable cost line — the advisor (Gemini) is NOT covered by the DeepSeek
    # TOKENCOST callback, so log its usage here. thoughtsTokenCount is the
    # thinking slice (billed at the output rate); it's 0 when thinking is off.
    try:
        usage = data.get("usageMetadata", {})
        in_tok = int(usage.get("promptTokenCount", 0))
        out_tok = int(usage.get("candidatesTokenCount", 0))
        think_tok = int(usage.get("thoughtsTokenCount", 0))
        logger.info(
            "GEMINICOST %s model=%s think_level=%s in=%d out=%d think=%d usd=%.5f",
            ticker or "-", model, level, in_tok, out_tok, think_tok,
            _gemini_cost_usd(in_tok, out_tok, think_tok),
        )
    except Exception:
        logger.debug("GEMINICOST logging failed", exc_info=True)

    # With thinking on, skip any thought part and return the first answer text.
    parts = data["candidates"][0]["content"]["parts"]
    for part in parts:
        if part.get("text") and not part.get("thought"):
            return part["text"]
    return parts[0].get("text", "")
