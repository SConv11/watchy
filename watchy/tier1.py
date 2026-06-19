"""Tier 1 — hourly signal scanner (data-only pre-filter, no LLM).

Fetches OHLCV + indicators, checks for signal breaches against thresholds and
cooldown windows, and fires the graduated analyst pipeline when a signal trips.
"""

from __future__ import annotations

import logging
from typing import Any

from watchy.advisor import get_advice
from watchy.config import WatchyConfig
from watchy.indicators import (
    IndicatorBundle,
    compute_indicators,
    compute_level_states,
    detect_signals,
)
from watchy.locks import TickerLockRegistry
from watchy.notify import TelegramNotifier
from watchy.orchestrator import (
    PipelineSpec,
    get_cooldown_hours,
    get_pipeline,
    run_pipeline,
)
from watchy.positions import get_position_source
from watchy.schwab_health import monitor_schwab
from watchy.state import StateStore

logger = logging.getLogger(__name__)


def scan_ticker(
    ticker: str,
    config: WatchyConfig,
    store: StateStore,
    notifier: TelegramNotifier,
    *,
    pipeline_runner: Any = None,
    ticker_locks: TickerLockRegistry | None = None,
) -> list[str]:
    """Run Tier 1 scan for a single ticker.

    Returns the list of signal types that fired (empty if none).
    """
    logger.info("Tier 1 scan start: %s", ticker)

    bundle = compute_indicators(ticker)
    if bundle is None:
        logger.warning("Skipping %s — no indicator data", ticker)
        return []

    prev = store.get_ticker_state(ticker)
    fired_signals = detect_signals(bundle, prev)

    # filter out signals still in cooldown
    actionable: list[str] = []
    for sig in fired_signals:
        cooldown_h = get_cooldown_hours(sig, config.cooldown)
        if store.is_in_cooldown(ticker, sig, cooldown_h):
            logger.info("Signal %s for %s in cooldown, skipping", sig, ticker)
            continue
        actionable.append(sig)

    if not actionable:
        _update_state(store, bundle, ticker)
        logger.info("Tier 1 scan complete: %s — no actionable signals", ticker)
        return []

    # Serialize the pipeline for this ticker so a concurrent Tier 2 run for the
    # same symbol doesn't double-spend the analyst budget or interleave state.
    lock = ticker_locks.get(ticker) if ticker_locks else _nullcontext()
    with lock:
        for sig in actionable:
            spec = get_pipeline(sig)
            _handle_signal(ticker, sig, spec, bundle, config, store, notifier, pipeline_runner)

    _update_state(store, bundle, ticker)
    logger.info("Tier 1 scan complete: %s — signals: %s", ticker, actionable)
    return actionable


def _nullcontext():
    from contextlib import nullcontext
    return nullcontext()


def _handle_signal(
    ticker: str,
    sig: str,
    spec: PipelineSpec,
    bundle: IndicatorBundle,
    config: WatchyConfig,
    store: StateStore,
    notifier: TelegramNotifier,
    pipeline_runner: Any = None,
) -> None:
    """Log the signal, notify, launch the analyst pipeline, and synthesize position advice."""
    details = _bundle_summary(bundle)
    store.log_signal(ticker, sig, details)

    # Tier 1 daily rescan cap (#23): each signal trip launches a paid pipeline +
    # advisor, guarded only by per-signal cooldown, so a ticker tripping several
    # distinct signals in a day stacks several paid rescans. Cap the count per UTC
    # day; further trips are logged + notified but skip the LLM pipeline.
    cap = _rescan_cap(ticker, config)
    if cap is not None:
        runs_today = store.count_tier1_runs_today(ticker)
        if runs_today >= cap:
            logger.info(
                "Tier 1 rescan capped for %s (%s): %d/%d runs today, skipping pipeline",
                ticker, sig, runs_today, cap,
            )
            notifier.rescan_capped(ticker, sig, details, runs_today, cap)
            return

    # notify: signal fired
    notifier.signal_fired(
        ticker, sig, details,
        triggered_analysts=_analyst_list_from_spec(spec),
    )

    # launch analysts
    run_id = store.start_run(ticker, "tier1", sig)
    try:
        # Fetch the position first (then run the expensive pipeline). This also
        # validates Schwab/OAuth up front: monitor_schwab reads the resolved
        # snapshot and alerts if it isn't live (expired token) or is nearing the
        # 7-day limit. (Holdings feed the advisor below, not TradingAgents.)
        position_source = get_position_source(config)
        position_text = position_source.format_position_context(ticker)
        monitor_schwab(config, store, notifier, position_source)

        result = run_pipeline(ticker, spec, runner=pipeline_runner)
        store.complete_run(run_id, success=True, summary=result.get("summary", ""))

        advice = get_advice(ticker, result, position_source, config)

        notifier.pipeline_result(
            ticker, sig, result,
            position_text=position_text,
            advice=advice,
        )
    except Exception as exc:
        logger.exception("Pipeline failed for %s: %s", ticker, exc)
        store.complete_run(run_id, success=False, summary=str(exc))
        notifier.error(f"Tier 1 pipeline: {ticker}/{sig}", exc)


def _update_state(
    store: StateStore,
    bundle: IndicatorBundle,
    ticker: str,
) -> None:
    store.save_ticker_state(
        ticker,
        prev_sma_50_above_200=(
            1 if bundle.sma_50 and bundle.sma_200 and bundle.sma_50 > bundle.sma_200
            else 0
        ),
        prev_macd_above_signal=(
            1 if bundle.macd and bundle.macd_signal and bundle.macd > bundle.macd_signal
            else 0
        ),
        prev_rsi=bundle.rsi,
        prev_atr=bundle.atr,
        avg_volume_20d=bundle.avg_volume_20d,
        avg_atr_20d=bundle.avg_atr_20d,
        # transition flags for level-based signals (#8)
        **compute_level_states(bundle),
    )


def _bundle_summary(bundle: IndicatorBundle) -> dict[str, Any]:
    return {
        "current_price": bundle.current_price,
        "sma_50": bundle.sma_50,
        "sma_200": bundle.sma_200,
        "rsi": bundle.rsi,
        "macd": bundle.macd,
        "macd_signal": bundle.macd_signal,
        "bb_upper": bundle.bb_upper,
        "bb_lower": bundle.bb_lower,
        "atr": bundle.atr,
        "volume": bundle.volume,
        "avg_volume_20d": bundle.avg_volume_20d,
        "sepa_stage": bundle.sepa_stage,
    }


def _analyst_list_from_spec(spec: PipelineSpec) -> list[str]:
    from watchy.orchestrator import _analyst_names
    return _analyst_names(spec.analysts)


def _rescan_cap(ticker: str, config: WatchyConfig) -> int | None:
    """Effective Tier 1 daily rescan cap: per-ticker override else global (#23)."""
    tc = config.get_ticker_config(ticker)
    if tc is not None and tc.max_tier1_pipelines_per_day is not None:
        return tc.max_tier1_pipelines_per_day
    return config.max_tier1_pipelines_per_day
