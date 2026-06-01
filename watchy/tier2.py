"""Tier 2 — scheduled daily full pipeline.

Runs the full TradingAgents 4-analyst pipeline (Market, Sentiment, News,
Fundamentals) with full debate and risk management for every ticker on the
watchlist.  Catches gradual drift and fundamental shifts that technical
triggers miss.
"""

from __future__ import annotations

import logging
from typing import Any

from watchy.advisor import get_advice
from watchy.config import WatchyConfig
from watchy.indicators import compute_indicators
from watchy.notify import TelegramNotifier
from watchy.orchestrator import AnalystSet, DebateMode, PipelineSpec, RiskMode, run_pipeline
from watchy.schwab import SchwabClient
from watchy.state import StateStore

logger = logging.getLogger(__name__)

FULL_PIPELINE = PipelineSpec(
    analysts=AnalystSet.FULL,
    debate=DebateMode.BULL_BEAR,
    risk=RiskMode.FULL,
)


def run_daily_scan(
    config: WatchyConfig,
    store: StateStore,
    notifier: TelegramNotifier,
    *,
    pipeline_runner: Any = None,
) -> dict[str, dict[str, Any]]:
    """Run Tier 2 for every ticker on the watchlist.

    Returns a dict mapping ticker → pipeline result.
    """
    results: dict[str, dict[str, Any]] = {}
    tickers = [tc.ticker for tc in config.watchlist]

    logger.info("Tier 2 daily scan starting for %d tickers", len(tickers))

    for ticker in tickers:
        try:
            results[ticker] = _run_ticker(ticker, config, store, notifier, pipeline_runner)
        except Exception as exc:
            logger.exception("Tier 2 failed for %s", ticker)
            notifier.error(f"Tier 2: {ticker}", exc)
            results[ticker] = {"error": str(exc)}

    succeeded = sum(1 for r in results.values() if "error" not in r)
    logger.info("Tier 2 daily scan complete: %d/%d succeeded", succeeded, len(tickers))
    return results


def _run_ticker(
    ticker: str,
    config: WatchyConfig,
    store: StateStore,
    notifier: TelegramNotifier,
    pipeline_runner: Any = None,
) -> dict[str, Any]:
    logger.info("Tier 2: %s", ticker)

    # enrich with indicators for stage context
    bundle = compute_indicators(ticker)
    stage_context = {}
    if bundle is not None:
        stage_context = {
            "sepa_stage": bundle.sepa_stage,
            "current_price": bundle.current_price,
            "sma_50": bundle.sma_50,
            "sma_200": bundle.sma_200,
            "rsi": bundle.rsi,
        }

    run_id = store.start_run(ticker, "tier2", "scheduled_daily")

    try:
        result = run_pipeline(ticker, FULL_PIPELINE, runner=pipeline_runner)
        if stage_context:
            result.setdefault("stage_context", stage_context)
        store.complete_run(run_id, success=True, summary=result.get("summary", ""))
        store.save_ticker_state(ticker, last_full_analysis_ts=_now_iso())

        # fetch position and synthesize advice
        schwab = SchwabClient(config.schwab)
        position_text = schwab.format_position_context(ticker)
        advice = get_advice(ticker, result, schwab, config)

        notifier.pipeline_result(
            ticker, "scheduled_daily", result,
            position_text=position_text,
            advice=advice,
        )
        return result
    except Exception as exc:
        store.complete_run(run_id, success=False, summary=str(exc))
        raise


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
