"""Tests for advisor: prompt formatting and advice parsing (no LLM calls)."""

import pytest

from watchy.advisor import (
    _analyst_summary_tail,
    _effective_key,
    _format_analysis,
    _gemini_cost_usd,
    _parse_advice,
)


class TestGeminiCost:
    def test_input_priced(self):
        assert abs(_gemini_cost_usd(1_000_000, 0, 0) - 1.50) < 1e-9

    def test_thinking_billed_as_output(self):
        # thinking tokens cost the same as visible output tokens
        assert _gemini_cost_usd(0, 0, 1_000_000) == _gemini_cost_usd(0, 1_000_000, 0)
        assert abs(_gemini_cost_usd(0, 0, 1_000_000) - 9.00) < 1e-9

    def test_zero(self):
        assert _gemini_cost_usd(0, 0, 0) == 0.0
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

    def test_decision_after_preamble_line(self):
        """A preamble before the header must not drop decision/urgency (AVGO bug)."""
        raw = (
            'Here is my assessment.\n\n'
            'Ticker: AVGO\nDecision: HOLD\nUrgency: LOW\n\n'
            'Wait for confirmation before adding.'
        )
        parsed = _parse_advice(raw, "AVGO")
        assert parsed["decision"] == "HOLD"
        assert parsed["urgency"] == "LOW"
        assert "Wait for confirmation" in parsed["detail"]
        assert "Here is my assessment" in parsed["detail"]

    def test_blank_first_line_still_parses(self):
        raw = "\nDecision: BUY\nUrgency: HIGH\n\nDetail here."
        parsed = _parse_advice(raw, "NVDA")
        assert parsed["decision"] == "BUY"
        assert parsed["urgency"] == "HIGH"
        assert parsed["detail"] == "Detail here."

    def test_no_header_lines(self):
        """If there are no Ticker:/Decision:/Urgency: lines, everything is detail."""
        raw = "Just a plain recommendation to BUY NVDA at these levels."
        parsed = _parse_advice(raw, "NVDA")
        assert parsed["ticker"] == "NVDA"
        assert parsed["decision"] == ""
        assert parsed["urgency"] == ""
        assert parsed["detail"] == raw


class TestAnalystSummaryTail:
    def test_returns_table_plus_trailing_conclusion(self):
        report = (
            "Long prose body about the stock.\n\nMore prose.\n\n"
            "| Signal | Direction |\n|---|---|\n| RSI | Bullish |\n\n"
            "FINAL TRANSACTION PROPOSAL: **BUY**\nReasoning: momentum holds.\n"
        )
        tail = _analyst_summary_tail(report)
        assert tail is not None
        assert "| Signal | Direction |" in tail          # the table
        assert "FINAL TRANSACTION PROPOSAL: **BUY**" in tail  # the conclusion after it
        assert "Reasoning: momentum holds." in tail
        assert "Long prose body" not in tail             # the prose before it is dropped

    def test_none_without_table(self):
        assert _analyst_summary_tail("Just prose, no table here.") is None

    def test_anchors_on_last_table(self):
        report = "| a | b |\n|---|---|\n\nmid\n\n| c | d |\n|---|---|\n| e | f |\n\nDONE\n"
        tail = _analyst_summary_tail(report)
        assert "| c | d |" in tail and "DONE" in tail
        assert "| a | b |" not in tail and "mid" not in tail


class TestFormatAnalysis:
    def test_feeds_summary_tail_not_full_prose(self):
        result = {
            "_reports": {
                "market_report": (
                    "LONG PROSE that must not be fed to the advisor. " * 20
                    + "\n\n| Metric | Value |\n|---|---|\n| Trend | Up |\n\n"
                    + "FINAL ASSESSMENT: accumulate.\n"
                ),
            },
        }
        text = _format_analysis(result)
        assert "| Trend | Up |" in text              # the summary table is fed
        assert "FINAL ASSESSMENT: accumulate." in text  # its trailing conclusion too
        assert "LONG PROSE" not in text              # the prose before the table is not

    def test_report_without_table_falls_back_to_head(self):
        result = {"_reports": {"news_report": "Headline-only note, no table."}}
        text = _format_analysis(result)
        assert "Headline-only note" in text

    def test_includes_trader_plan(self):
        result = {"trader_plan": "**Action**: Buy\n**Entry Price**: 180"}
        text = _format_analysis(result)
        assert "Entry Price" in text and "180" in text

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
