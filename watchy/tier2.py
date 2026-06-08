"""Tier 2 — scheduled daily pipeline.

Runs the full TradingAgents 4-analyst pipeline (Market, Sentiment, News,
Fundamentals) with Bull/Bear debate for every ticker on the watchlist, catching
gradual drift and fundamental shifts that technical triggers miss.

Risk depth is day-of-week dependent (#14): simplified risk on weekdays, the full
3-way risk debate on Sundays. See orchestrator.get_scheduled_spec.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from watchy.advisor import get_advice
from watchy.config import WatchyConfig
from watchy.indicators import compute_indicators
from watchy.locks import TickerLockRegistry
from watchy.notify import TelegramNotifier
from watchy.orchestrator import get_scheduled_spec, run_pipeline
from watchy.positions import get_position_source
from watchy.state import StateStore

logger = logging.getLogger(__name__)


def run_daily_scan(
    config: WatchyConfig,
    store: StateStore,
    notifier: TelegramNotifier,
    *,
    pipeline_runner: Any = None,
    ticker_locks: TickerLockRegistry | None = None,
) -> dict[str, dict[str, Any]]:
    """Run Tier 2 for every ticker on the watchlist.

    Returns a dict mapping ticker → pipeline result.
    """
    results: dict[str, dict[str, Any]] = {}
    tickers = [tc.ticker for tc in config.watchlist]

    logger.info("Tier 2 daily scan starting for %d tickers", len(tickers))

    for i, ticker in enumerate(tickers):
        if i > 0 and config.tier2_throttle_s > 0:
            time.sleep(config.tier2_throttle_s)
        try:
            results[ticker] = _run_ticker(
                ticker, config, store, notifier, pipeline_runner, ticker_locks,
            )
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
    ticker_locks: TickerLockRegistry | None = None,
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

    # Serialize against a concurrent Tier 1 pipeline for the same ticker.
    from contextlib import nullcontext
    lock = ticker_locks.get(ticker) if ticker_locks else nullcontext()

    spec = get_scheduled_spec(datetime.now(timezone.utc))

    with lock:
        run_id = store.start_run(ticker, "tier2", "scheduled_daily")
        try:
            result = run_pipeline(ticker, spec, runner=pipeline_runner)
            if stage_context:
                result.setdefault("stage_context", stage_context)
            store.complete_run(run_id, success=True, summary=result.get("summary", ""))
            store.save_ticker_state(ticker, last_full_analysis_ts=_now_iso())

            # fetch position and synthesize advice
            position_source = get_position_source(config)
            position_text = position_source.format_position_context(ticker)
            advice = get_advice(ticker, result, position_source, config)

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
