"""Graduated analyst pipeline selection per trigger type.

Maps each signal trigger to the appropriate subset of TradingAgents analysts,
debate configuration, and risk management level.

Based on the architecture: different signals warrant different depths of
LLM-based analysis depending on their rarity and significance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AnalystSet(Enum):
    """Which TradingAgents analysts to invoke."""
    NONE = "none"
    MARKET_ONLY = "market_only"           # just Market analyst for quick check
    MARKET_SENTIMENT = "market_sentiment"  # Market + Sentiment
    MARKET_SENTIMENT_NEWS = "market_sentiment_news"  # + News for structural events
    FULL = "full"                          # all 4: Market, Sentiment, News, Fundamentals


class DebateMode(Enum):
    """Debate configuration."""
    NONE = "none"       # analyst output only, no opposing views
    BULL_BEAR = "bull_bear"  # full Bull vs Bear debate


class RiskMode(Enum):
    """Risk management depth."""
    NONE = "none"              # skip risk (analyst output is final)
    SIMPLIFIED = "simplified"  # portfolio manager evaluates trader directly
    FULL = "full"              # 3-way aggressive/conservative/neutral debate


@dataclass
class PipelineSpec:
    """What to run for a given trigger."""
    analysts: AnalystSet
    debate: DebateMode
    risk: RiskMode


# --- Signal → Pipeline mapping ---
#
# NOTE: the Tier 2 scheduled run is NOT a key here — its depth depends on the day
# of week (see get_scheduled_spec). get_pipeline("scheduled_daily") delegates to
# that helper so the trigger-type string still resolves correctly.

SIGNAL_PIPELINE: dict[str, PipelineSpec] = {
    # Golden/Death Cross — rare structural events, add News + full risk
    "golden_cross": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT_NEWS,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.FULL,
    ),
    "death_cross": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT_NEWS,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.FULL,
    ),

    # RSI extremes — Market + Sentiment, simplified risk
    "rsi_oversold": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.SIMPLIFIED,
    ),
    "rsi_overbought": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.SIMPLIFIED,
    ),

    # MACD crossover — Market + Sentiment, simplified risk
    "macd_bullish_cross": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.SIMPLIFIED,
    ),
    "macd_bearish_cross": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.SIMPLIFIED,
    ),

    # Bollinger breach — Market + Sentiment, simplified risk
    "bollinger_upper_breach": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.SIMPLIFIED,
    ),
    "bollinger_lower_breach": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.SIMPLIFIED,
    ),

    # Volume anomaly strong — Market + Sentiment, simplified risk
    "volume_anomaly_strong": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.SIMPLIFIED,
    ),

    # ATR spike — Market + Sentiment, simplified risk
    "atr_spike": PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.SIMPLIFIED,
    ),
}


def get_scheduled_spec(when: datetime) -> PipelineSpec:
    """Pipeline spec for a Tier 2 scheduled daily run (#14).

    Daily (any weekday): the full 4-analyst set (Market, Sentiment, News,
    Fundamentals) + Bull/Bear debate + *simplified* risk.

    Sundays (``weekday() == 6``): escalate to ``RiskMode.FULL`` — the 3-way
    Aggressive/Conservative/Neutral risk debate — so every ticker gets guaranteed
    weekly risk-debate coverage. The debate is expensive, hence weekly not daily.
    """
    return PipelineSpec(
        analysts=AnalystSet.FULL,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.FULL if when.weekday() == 6 else RiskMode.SIMPLIFIED,
    )


def get_pipeline(signal_type: str) -> PipelineSpec:
    """Return the pipeline spec for a signal type.

    The Tier 2 ``"scheduled_daily"`` trigger delegates to get_scheduled_spec
    (its depth is day-of-week dependent). Unknown signals fall back to
    MARKET_SENTIMENT + simplified risk.
    """
    if signal_type == "scheduled_daily":
        return get_scheduled_spec(datetime.now(timezone.utc))

    spec = SIGNAL_PIPELINE.get(signal_type)
    if spec is not None:
        return spec

    logger.warning(
        "Unknown signal type '%s', falling back to Market+Sentiment", signal_type
    )
    return PipelineSpec(
        analysts=AnalystSet.MARKET_SENTIMENT,
        debate=DebateMode.BULL_BEAR,
        risk=RiskMode.SIMPLIFIED,
    )


def get_cooldown_hours(signal_type: str, cooldown_config: Any) -> float:
    """Return cooldown in hours for a signal type."""
    cfg = cooldown_config
    mapping: dict[str, float] = {
        "golden_cross": cfg.golden_cross_d * 24,
        "death_cross": cfg.golden_cross_d * 24,
        "rsi_oversold": cfg.rsi_extreme_h,
        "rsi_overbought": cfg.rsi_extreme_h,
        "macd_bullish_cross": cfg.macd_cross_h,
        "macd_bearish_cross": cfg.macd_cross_h,
        "bollinger_upper_breach": cfg.bollinger_breach_h,
        "bollinger_lower_breach": cfg.bollinger_breach_h,
        "volume_anomaly_strong": cfg.volume_anomaly_h,
        "atr_spike": cfg.atr_spike_h,
    }
    return mapping.get(signal_type, 4.0)


# --- TradingAgents pipeline runner (stub — wired to real TradingAgents on VPS) ---

PipelineRunner = Callable[[str, PipelineSpec], dict[str, Any]]


def run_pipeline(
    ticker: str,
    spec: PipelineSpec,
    *,
    runner: PipelineRunner | None = None,
) -> dict[str, Any]:
    """Execute the appropriate TradingAgents pipeline for a ticker.

    Args:
        ticker: The ticker symbol.
        spec: Which analysts/debate/risk to run.
        runner: Callable that actually invokes TradingAgents. If None, uses
                a stub that logs what would have run.

    Returns:
        Dict with keys: ticker, analysts_run, recommendations, trader_plan,
        risk_assessment, summary.
    """
    analysts_list = _analyst_names(spec.analysts)
    logger.info(
        "Launching pipeline for %s: analysts=%s debate=%s risk=%s",
        ticker, spec.analysts.value, spec.debate.value, spec.risk.value,
    )

    if runner is not None:
        return runner(ticker, spec)

    # Stub — replace with real TradingAgents integration on VPS
    return {
        "ticker": ticker,
        "analysts_run": analysts_list,
        "debate": spec.debate.value,
        "risk_mode": spec.risk.value,
        "recommendations": [],
        "risk_assessment": None,
        "summary": (
            f"[STUB] Would run {', '.join(analysts_list)} analysts for {ticker} "
            f"with {spec.debate.value} debate and {spec.risk.value} risk management."
        ),
    }


def _analyst_names(analyst_set: AnalystSet) -> list[str]:
    mapping = {
        AnalystSet.NONE: [],
        AnalystSet.MARKET_ONLY: ["market"],
        AnalystSet.MARKET_SENTIMENT: ["market", "sentiment"],
        AnalystSet.MARKET_SENTIMENT_NEWS: ["market", "sentiment", "news"],
        AnalystSet.FULL: ["market", "sentiment", "news", "fundamentals"],
    }
    return mapping.get(analyst_set, [])
