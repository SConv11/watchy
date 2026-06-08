"""Tier 1 — hourly signal scanner (data-only pre-filter, no LLM).

Fetches OHLCV + indicators, checks for signal breaches against thresholds and
cooldown windows, and fires the graduated analyst pipeline when a signal trips.
"""

from __future__ import annotations

import logging
from typing import Any

from watchy.advisor import get_advice
from watchy.config import TickerConfig, WatchyConfig
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

    # Per-ticker price-proximity skip (#5): when a target price + proximity are
    # configured, skip tickers trading far from the level the user cares about.
    tc = config.get_ticker_config(ticker)
    if _is_outside_proximity(bundle.current_price, tc):
        logger.info(
            "Tier 1 skip %s — price %.2f outside %.2f%% of target %.2f",
            ticker, bundle.current_price,
            tc.tier1_min_price_proximity_pct, tc.target_price,
        )
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


def _is_outside_proximity(price: float | None, tc: TickerConfig | None) -> bool:
    """True if a target/proximity is configured and price is too far from target.

    Returns False (never skip) when the feature isn't configured for this ticker,
    when there's no price, or on a non-positive target.
    """
    if tc is None or tc.target_price is None or tc.tier1_min_price_proximity_pct is None:
        return False
    if not price or tc.target_price <= 0:
        return False
    distance_pct = abs(price - tc.target_price) / tc.target_price * 100
    return distance_pct > tc.tier1_min_price_proximity_pct


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

    # notify: signal fired
    notifier.signal_fired(
        ticker, sig, details,
        triggered_analysts=_analyst_list_from_spec(spec),
    )

    # launch analysts
    run_id = store.start_run(ticker, "tier1", sig)
    try:
        result = run_pipeline(ticker, spec, runner=pipeline_runner)
        store.complete_run(run_id, success=True, summary=result.get("summary", ""))

        # fetch position and synthesize advice
        position_source = get_position_source(config)
        position_text = position_source.format_position_context(ticker)
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
