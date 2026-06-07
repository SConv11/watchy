"""Tests for advisor: prompt formatting and advice parsing (no LLM calls)."""

import pytest

from watchy.advisor import _effective_key, _format_analysis, _parse_advice
from watchy.config import LLMConfig


class TestEffectiveKey:
    def test_deepseek_uses_deepseek_key(self):
        llm = LLMConfig(provider="deepseek", deepseek_api_key="ds-secret", api_key="")
        assert _effective_key(llm) == "ds-secret"

    def test_deepseek_falls_back_to_api_key(self):
        llm = LLMConfig(provider="deepseek", deepseek_api_key="", api_key="generic")
        assert _effective_key(llm) == "generic"

    def test_anthropic_uses_api_key(self):
        llm = LLMConfig(provider="anthropic", api_key="sk-ant", deepseek_api_key="ignored")
        assert _effective_key(llm) == "sk-ant"

    def test_both_empty_returns_empty(self):
        llm = LLMConfig(provider="deepseek", deepseek_api_key="", api_key="")
        assert _effective_key(llm) == ""


class TestParseAdvice:
    def test_parses_standard_format(self):
        raw = """Ticker: NVDA
Decision: BUY
Urgency: HIGH

NVDA is trading at $142 with RSI oversold at 26. I recommend a 2% allocation
with a stop-loss at $128 targeting $165-$170. Primary risk is upcoming earnings
on June 18. If it breaks below $135 before earnings, exit early."""
        parsed = _parse_advice(raw, "NVDA")
        assert parsed["ticker"] == "NVDA"
        assert parsed["decision"] == "BUY"
        assert parsed["urgency"] == "HIGH"
        assert "RSI oversold" in parsed["detail"]
        assert "stop-loss" in parsed["detail"]

    def test_parses_sell(self):
        raw = """Ticker: TSLA
Decision: SELL
Urgency: MEDIUM

Death cross confirmed with declining fundamentals. Exit full position at $245,
locking in gains before potential drop to $200."""
        parsed = _parse_advice(raw, "TSLA")
        assert parsed["ticker"] == "TSLA"
        assert parsed["decision"] == "SELL"
        assert parsed["urgency"] == "MEDIUM"

    def test_parses_hold(self):
        raw = """Ticker: AAPL
Decision: HOLD
Urgency: LOW

Price near fair value, no strong directional signals. Maintain current position."""
        parsed = _parse_advice(raw, "AAPL")
        assert parsed["decision"] == "HOLD"
        assert parsed["urgency"] == "LOW"

    def test_fallback_ticker_when_missing(self):
        raw = """Decision: BUY
Urgency: HIGH

Some detail here."""
        parsed = _parse_advice(raw, "FALLBACK")
        assert parsed["ticker"] == "FALLBACK"
        assert parsed["decision"] == "BUY"

    def test_case_insensitive_labels(self):
        raw = """ticker: nvda
decision: buy
urgency: high

detail"""
        parsed = _parse_advice(raw, "NVDA")
        assert parsed["ticker"] == "nvda"  # preserves case of value
        assert parsed["decision"] == "BUY"  # uppercased
        assert parsed["urgency"] == "HIGH"

    def test_no_header_lines(self):
        """If there are no Ticker:/Decision:/Urgency: lines, everything is detail."""
        raw = "Just a plain recommendation to BUY NVDA at these levels."
        parsed = _parse_advice(raw, "NVDA")
        assert parsed["ticker"] == "NVDA"
        assert parsed["decision"] == ""
        assert parsed["urgency"] == ""
        assert parsed["detail"] == raw


class TestFormatAnalysis:
    def test_full_reports_preferred(self):
        result = {
            "_reports": {
                "market_report": "Market analysis full text.",
                "sentiment_report": "Sentiment analysis full text.",
            },
            "recommendations": ["truncated market...", "truncated sentiment..."],
        }
        text = _format_analysis(result)
        assert "Market analysis full text" in text
        assert "Sentiment analysis full text" in text

    def test_falls_back_to_recommendations(self):
        result = {
            "_reports": {},
            "recommendations": ["[Market] truncated...", "[Sentiment] truncated..."],
        }
        text = _format_analysis(result)
        assert "truncated" in text

    def test_includes_risk_assessment(self):
        result = {
            "_reports": {},
            "risk_assessment": "Risk is moderate due to sector rotation.",
        }
        text = _format_analysis(result)
        assert "Risk is moderate" in text

    def test_includes_decision(self):
        result = {
            "_reports": {},
            "_decision_raw": "FINAL: BUY with 2% position size.",
        }
        text = _format_analysis(result)
        assert "FINAL: BUY" in text

    def test_includes_sepa_stage(self):
        result = {
            "_reports": {},
            "stage_context": {"sepa_stage": 2},
        }
        text = _format_analysis(result)
        assert "Advancing" in text

    def test_empty_result_returns_json(self):
        result = {}
        text = _format_analysis(result)
        assert text == "{}"
