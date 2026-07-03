"""Per-component token + cost tracking for the TradingAgents pipeline.

A LangChain callback handler that attributes DeepSeek token usage to both the
*model* (deep_think v4-pro vs quick_think v4-flash) and the *graph node* (which
analyst / debater / manager made the call), so we can see where the daily Tier 2
cost actually goes before deciding what to trim.

Also breaks out the *reasoning* (thinking/CoT) slice of the output tokens per
model and node — DeepSeek V4 runs every node in thinking mode by default and
bills the CoT as completion tokens, so this shows how much of the bill is
thinking (and thus how much disabling it on a node could save).

Wired in via ``TradingAgentsGraph(..., callbacks=[TokenCostTracker()])`` — the
graph passes the handler to both LLM constructors (see trading_graph.py), so a
single instance sees every call. Every handler body is exception-safe: a bug
here must never break a live pipeline run, only lose a measurement.

Prices are the DeepSeek V4 published rates (USD per 1M tokens). Absolute USD is a
*relative proxy* for the CNY bill — what we care about is the per-component
*share*, which is currency-independent.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# DeepSeek V4 prices, USD per 1M tokens (see watchy-api-cost-baseline memory).
# cache-miss input / cache-hit input / output.
_PRICES = {
    "pro": {"in": 0.435, "cache": 0.003625, "out": 0.87},
    "flash": {"in": 0.14, "cache": 0.0028, "out": 0.28},
}


def _price_tier(model: str) -> str:
    """Map a model name to a price tier; default to the cheaper 'flash'."""
    return "pro" if model and "pro" in model.lower() else "flash"


def _cost_usd(model: str, input_tok: int, cached_tok: int, output_tok: int) -> float:
    p = _PRICES[_price_tier(model)]
    miss = max(input_tok - cached_tok, 0)
    return (miss * p["in"] + cached_tok * p["cache"] + output_tok * p["out"]) / 1_000_000


class _Bucket:
    __slots__ = ("calls", "input", "cached", "output", "reasoning", "usd")

    def __init__(self) -> None:
        self.calls = self.input = self.cached = self.output = self.reasoning = 0
        self.usd = 0.0

    def add(
        self,
        model: str,
        input_tok: int,
        cached_tok: int,
        output_tok: int,
        reasoning_tok: int = 0,
    ) -> None:
        self.calls += 1
        self.input += input_tok
        self.cached += cached_tok
        self.output += output_tok
        # reasoning_tok is a *subset* of output_tok (DeepSeek/OpenAI bill the CoT
        # as completion tokens), tracked separately only to see the thinking share.
        self.reasoning += reasoning_tok
        self.usd += _cost_usd(model, input_tok, cached_tok, output_tok)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "in": self.input,
            "cache": self.cached,
            "out": self.output,
            "reason": self.reasoning,
            "usd": round(self.usd, 5),
        }


# langchain-core BaseCallbackHandler; deferred import so the module is importable
# without langchain (unit tests on a bare machine).
try:  # pragma: no cover - import shim
    from langchain_core.callbacks import BaseCallbackHandler as _Base
except Exception:  # pragma: no cover
    _Base = object


class TokenCostTracker(_Base):
    """Accumulates DeepSeek token usage per model and per graph node."""

    def __init__(self) -> None:
        # run_id -> (model, node) captured at start, consumed at end.
        self._inflight: dict[Any, tuple[str, str]] = {}
        self.by_model: dict[str, _Bucket] = defaultdict(_Bucket)
        self.by_node: dict[str, _Bucket] = defaultdict(_Bucket)

    # --- start hooks: record model + node for this run_id --------------------
    def _on_start(self, run_id: Any, metadata: Any, kwargs: dict) -> None:
        try:
            meta = metadata or {}
            model = (
                meta.get("ls_model_name")
                or (kwargs.get("invocation_params") or {}).get("model")
                or (kwargs.get("invocation_params") or {}).get("model_name")
                or "unknown"
            )
            node = meta.get("langgraph_node") or "unknown"
            self._inflight[run_id] = (str(model), str(node))
        except Exception:
            logger.debug("TokenCostTracker start hook failed", exc_info=True)

    def on_chat_model_start(self, serialized, messages, *, run_id=None, metadata=None, **kwargs):  # noqa: D102
        self._on_start(run_id, metadata, kwargs)

    def on_llm_start(self, serialized, prompts, *, run_id=None, metadata=None, **kwargs):  # noqa: D102
        self._on_start(run_id, metadata, kwargs)

    # --- end hook: read usage off the response and attribute ----------------
    def on_llm_end(self, response, *, run_id=None, **kwargs):  # noqa: D102
        try:
            model, node = self._inflight.pop(run_id, ("unknown", "unknown"))
            input_tok, cached_tok, output_tok, reasoning_tok, model_from_resp = _extract_usage(response)
            if model == "unknown" and model_from_resp:
                model = model_from_resp
            if input_tok == 0 and output_tok == 0:
                return
            self.by_model[_price_tier(model)].add(model, input_tok, cached_tok, output_tok, reasoning_tok)
            self.by_node[node].add(model, input_tok, cached_tok, output_tok, reasoning_tok)
        except Exception:
            logger.debug("TokenCostTracker end hook failed", exc_info=True)

    # --- reporting ----------------------------------------------------------
    def total_usd(self) -> float:
        return sum(b.usd for b in self.by_model.values())

    def log_summary(self, ticker: str, label: str) -> None:
        """Emit one compact, greppable TOKENCOST line for this pipeline run."""
        try:
            if not self.by_model:
                return
            models = {k: v.as_dict() for k, v in self.by_model.items()}
            nodes = {k: v.as_dict() for k, v in sorted(self.by_node.items())}
            logger.info(
                "TOKENCOST %s [%s] usd=%.4f models=%s nodes=%s",
                ticker,
                label,
                self.total_usd(),
                json.dumps(models, separators=(",", ":")),
                json.dumps(nodes, separators=(",", ":")),
            )
        except Exception:
            logger.debug("TokenCostTracker log_summary failed", exc_info=True)


def _extract_usage(response: Any) -> tuple[int, int, int, int, str]:
    """Pull (input, cached, output, reasoning, model) from an LLMResult, defensively.

    Prefers the normalized ``usage_metadata`` on the chat message (langchain-core
    1.x); falls back to ``llm_output['token_usage']`` (OpenAI-style dict).

    ``reasoning`` is the thinking/CoT slice of ``output`` (DeepSeek V4 thinking
    mode, OpenAI reasoning models) — a subset of ``output``, not additive.
    """
    model = ""
    try:
        llm_output = getattr(response, "llm_output", None) or {}
        model = llm_output.get("model_name") or llm_output.get("model") or ""
    except Exception:
        llm_output = {}

    # Preferred: usage_metadata on the message.
    try:
        for gen_list in getattr(response, "generations", []) or []:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                um = getattr(msg, "usage_metadata", None)
                if um:
                    input_tok = int(um.get("input_tokens", 0))
                    output_tok = int(um.get("output_tokens", 0))
                    details = um.get("input_token_details") or {}
                    cached_tok = int(details.get("cache_read", 0))
                    out_details = um.get("output_token_details") or {}
                    reasoning_tok = int(out_details.get("reasoning", 0))
                    return input_tok, cached_tok, output_tok, reasoning_tok, model
    except Exception:
        pass

    # Fallback: OpenAI-style token_usage dict.
    try:
        tu = (llm_output or {}).get("token_usage") or {}
        if tu:
            input_tok = int(tu.get("prompt_tokens", 0))
            output_tok = int(tu.get("completion_tokens", 0))
            details = tu.get("prompt_tokens_details") or {}
            cached_tok = int(details.get("cached_tokens", 0))
            out_details = tu.get("completion_tokens_details") or {}
            reasoning_tok = int(out_details.get("reasoning_tokens", 0))
            return input_tok, cached_tok, output_tok, reasoning_tok, model
    except Exception:
        pass

    return 0, 0, 0, 0, model
