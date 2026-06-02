"""Watchy daemon — main entry point with APScheduler setup.

Two scheduled jobs:
  Tier 1 — runs per-ticker on configurable hourly intervals
  Tier 2 — runs once daily per ticker at configured UTC time
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from watchy import __version__
from watchy.config import WatchyConfig, load_config
from watchy.notify import TelegramNotifier
from watchy.state import StateStore
from watchy.pipeline_runner import create_tradingagents_runner
from watchy.tier1 import scan_ticker
from watchy.tier2 import run_daily_scan


def setup_logging(config: WatchyConfig) -> None:
    log_file = os.path.expanduser(config.log_file)
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def build_scheduler(
    config: WatchyConfig,
    store: StateStore,
    notifier: TelegramNotifier,
    *,
    pipeline_runner: Any = None,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")

    # Tier 1: per-ticker hourly scans
    for tc in config.watchlist:
        scheduler.add_job(
            _tier1_job,
            trigger=IntervalTrigger(hours=tc.tier1_interval_h),
            args=[tc.ticker, config, store, notifier, pipeline_runner],
            id=f"tier1_{tc.ticker}",
            name=f"Tier 1 — {tc.ticker}",
            replace_existing=True,
        )

    # Tier 2: one job per unique UTC time (processes all tickers in that slot)
    seen_times: set[str] = set()
    for tc in config.watchlist:
        if tc.tier2_time_utc in seen_times:
            continue
        seen_times.add(tc.tier2_time_utc)
        hour, minute = tc.tier2_time_utc.split(":")
        scheduler.add_job(
            _tier2_job,
            trigger=CronTrigger(hour=int(hour), minute=int(minute)),
            args=[config, store, notifier, pipeline_runner],
            id=f"tier2_{tc.tier2_time_utc.replace(':', '')}",
            name=f"Tier 2 — {tc.tier2_time_utc} UTC",
            replace_existing=True,
        )

    return scheduler


def _tier1_job(
    ticker: str,
    config: WatchyConfig,
    store: StateStore,
    notifier: TelegramNotifier,
    pipeline_runner: Any = None,
) -> None:
    logger = logging.getLogger("watchy.daemon")
    try:
        fired = scan_ticker(
            ticker, config, store, notifier, pipeline_runner=pipeline_runner,
        )
        if fired:
            logger.info("Tier 1 %s: fired %s", ticker, fired)
    except Exception:
        logger.exception("Tier 1 job failed for %s", ticker)
        notifier.error(f"Tier 1 job: {ticker}", sys.exc_info()[1])


def _tier2_job(
    config: WatchyConfig,
    store: StateStore,
    notifier: TelegramNotifier,
    pipeline_runner: Any = None,
) -> None:
    logger = logging.getLogger("watchy.daemon")
    try:
        run_daily_scan(config, store, notifier, pipeline_runner=pipeline_runner)
    except Exception:
        logger.exception("Tier 2 job failed")
        notifier.error("Tier 2 job", sys.exc_info()[1])


def main(config_path: str | None = None) -> None:
    config = load_config(config_path)
    setup_logging(config)
    logger = logging.getLogger("watchy.daemon")

    logger.info("Watchy %s starting", __version__)
    logger.info("Watchlist: %s", [tc.ticker for tc in config.watchlist])

    store = StateStore()
    notifier = TelegramNotifier(config.telegram.bot_token, config.telegram.chat_id)

    # Wire the real TradingAgents pipeline runner (DeepSeek by default).
    # API key from secrets.yaml, injected as env var before TA imports.
    pipeline_runner = create_tradingagents_runner(
        deepseek_api_key=config.llm.deepseek_api_key,
    )

    scheduler = build_scheduler(
        config, store, notifier, pipeline_runner=pipeline_runner,
    )

    def _shutdown(signum, frame):
        logger.info("Shutting down (signal=%d)", signum)
        scheduler.shutdown(wait=False)
        store.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

    try:
        # keep alive — scheduler runs in background thread
        signal.pause()
    except AttributeError:
        # Windows doesn't have signal.pause()
        import time
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
