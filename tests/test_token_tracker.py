"""Tests for the TokenCostTracker callback: usage extraction, attribution, cost."""

from types import SimpleNamespace

from watchy.token_tracker import (
    TokenCostTracker,
    _cost_usd,
    _extract_usage,
    _price_tier,
)


def _resp(model, input_tok, output_tok, cache_read=0):
    """Build a minimal LLMResult-like object with usage_metadata on the message."""
    msg = SimpleNamespace(
        usage_metadata={
            "input_tokens": input_tok,
            "output_tokens": output_tok,
            "input_token_details": {"cache_read": cache_read},
        }
    )
    gen = SimpleNamespace(message=msg)
    return SimpleNamespace(generations=[[gen]], llm_output={"model_name": model})


class TestPriceTier:
    def test_pro_detected(self):
        assert _price_tier("deepseek-v4-pro") == "pro"

    def test_flash_default(self):
        assert _price_tier("deepseek-v4-flash") == "flash"
        assert _price_tier("") == "flash"
        assert _price_tier("something-unknown") == "flash"


class TestCost:
    def test_flash_cost_math(self):
        # 1M miss input + 1M output, no cache → 0.14 + 0.28 = 0.42
        assert abs(_cost_usd("flash", 1_000_000, 0, 1_000_000) - 0.42) < 1e-9

    def test_cache_hit_is_cheaper(self):
        full = _cost_usd("flash", 1_000_000, 0, 0)
        cached = _cost_usd("flash", 1_000_000, 1_000_000, 0)
        assert cached < full
        assert abs(cached - 0.0028) < 1e-9

    def test_pro_dearer_than_flash(self):
        assert _cost_usd("pro", 1_000_000, 0, 1_000_000) > _cost_usd(
            "flash", 1_000_000, 0, 1_000_000
        )


class TestExtractUsage:
    def test_reads_usage_metadata(self):
        inp, cached, out, model = _extract_usage(_resp("deepseek-v4-pro", 100, 40, 25))
        assert (inp, cached, out, model) == (100, 25, 40, "deepseek-v4-pro")

    def test_openai_style_fallback(self):
        resp = SimpleNamespace(
            generations=[[SimpleNamespace(message=SimpleNamespace(usage_metadata=None))]],
            llm_output={
                "model_name": "deepseek-v4-flash",
                "token_usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 50,
                    "prompt_tokens_details": {"cached_tokens": 30},
                },
            },
        )
        inp, cached, out, model = _extract_usage(resp)
        assert (inp, cached, out) == (200, 30, 50)

    def test_empty_response_is_zero(self):
        resp = SimpleNamespace(generations=[], llm_output={})
        assert _extract_usage(resp) == (0, 0, 0, "")


class TestTrackerAttribution:
    def _run(self, tracker, run_id, model, node, input_tok, output_tok, cache=0):
        tracker.on_chat_model_start(
            {}, [], run_id=run_id, metadata={"langgraph_node": node, "ls_model_name": model}
        )
        tracker.on_llm_end(_resp(model, input_tok, output_tok, cache), run_id=run_id)

    def test_attributes_by_model_and_node(self):
        t = TokenCostTracker()
        self._run(t, "r1", "deepseek-v4-flash", "Market Analyst", 1000, 200)
        self._run(t, "r2", "deepseek-v4-pro", "Research Manager", 500, 300)

        assert t.by_node["Market Analyst"].calls == 1
        assert t.by_node["Research Manager"].input == 500
        assert t.by_model["flash"].output == 200
        assert t.by_model["pro"].output == 300
        # pro call should dominate cost despite fewer tokens
        assert t.by_model["pro"].usd > 0
        assert abs(t.total_usd() - (t.by_model["pro"].usd + t.by_model["flash"].usd)) < 1e-12

    def test_node_falls_back_to_unknown(self):
        t = TokenCostTracker()
        t.on_chat_model_start({}, [], run_id="x", metadata=None)
        t.on_llm_end(_resp("deepseek-v4-flash", 10, 5), run_id="x")
        assert t.by_node["unknown"].calls == 1

    def test_zero_usage_not_recorded(self):
        t = TokenCostTracker()
        t.on_chat_model_start({}, [], run_id="x", metadata={"langgraph_node": "n"})
        t.on_llm_end(SimpleNamespace(generations=[], llm_output={}), run_id="x")
        assert "n" not in t.by_node

    def test_log_summary_no_calls_is_safe(self):
        TokenCostTracker().log_summary("AAPL", "lbl")  # must not raise
