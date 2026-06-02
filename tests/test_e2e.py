#!/usr/bin/env python
"""End-to-end smoke test: trigger TradingAgents analysis → Gemini advice → Telegram.

Usage:
    python tests/test_e2e.py NVDA                          # single ticker
    python tests/test_e2e.py NVDA --signal rsi_oversold    # with specific signal

Requires:
    - DEEPSEEK_API_KEY in environment (TradingAgents)
    - ~/watchy_config/secrets.yaml with llm + telegram sections
    - TradingAgents installed (pip install -e ~/TradingAgents)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure the watchy package is importable from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from watchy.advisor import get_advice
from watchy.config import load_config
from watchy.notify import TelegramNotifier
from watchy.orchestrator import PipelineSpec, get_pipeline
from watchy.pipeline_runner import create_tradingagents_runner
from watchy.schwab import SchwabClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("e2e")


def main() -> None:
    parser = argparse.ArgumentParser(description="Watchy end-to-end smoke test")
    parser.add_argument("ticker", help="Ticker symbol, e.g. NVDA")
    parser.add_argument(
        "--signal", default="scheduled_daily",
        help="Signal type to simulate (default: scheduled_daily)",
    )
    args = parser.parse_args()

    ticker = args.ticker.upper()
    signal_type = args.signal

    # ---- 1. Load config ----
    logger.info("Loading config...")
    try:
        config = load_config()
    except FileNotFoundError:
        logger.error("Config not found. Copy config.yaml + secrets.yaml to ~/watchy_config/")
        sys.exit(1)

    # ---- 2. Check preconditions ----
    if not config.telegram.bot_token:
        logger.warning("No Telegram token in secrets.yaml — notifications will be logged only")
    if not config.llm.api_key:
        logger.warning("No LLM API key in secrets.yaml — advisor will be skipped")
    logger.info("Watchlist: %s", [tc.ticker for tc in config.watchlist])

    # ---- 3. Create the real pipeline runner (DeepSeek) ----
    logger.info("Creating TradingAgents pipeline runner (DeepSeek)...")
    runner = create_tradingagents_runner()

    # ---- 4. Resolve PipelineSpec ----
    spec = get_pipeline(signal_type)
    logger.info(
        "Signal: %s → analysts=%s debate=%s risk=%s",
        signal_type, spec.analysts.value, spec.debate.value, spec.risk.value,
    )

    # ---- 5. Run TradingAgents ----
    logger.info("Running TradingAgents analysis for %s...", ticker)
    result = runner(ticker, spec)
    logger.info("TA complete. Analysts: %s", result.get("analysts_run"))
    report_path = result.get("report_path", "N/A")
    logger.info("Report saved: %s", report_path)

    # ---- 6. Gemini advisor ----
    logger.info("Synthesizing advice (Gemini)...")
    schwab = SchwabClient(config.schwab)
    advice = get_advice(ticker, result, schwab, config)
    if advice:
        logger.info(
            "Advice: decision=%s urgency=%s",
            advice.get("decision"), advice.get("urgency"),
        )
    else:
        logger.warning("No advice generated (check LLM config)")

    # ---- 7. Telegram notification ----
    logger.info("Sending to Telegram...")
    notifier = TelegramNotifier(config.telegram.bot_token, config.telegram.chat_id)
    position_text = schwab.format_position_context(ticker)
    ok = notifier.pipeline_result(
        ticker, signal_type, result,
        position_text=position_text,
        advice=advice,
    )
    if ok:
        logger.info("Telegram notification sent!")
    else:
        logger.info("Telegram not configured — notification logged to console only (see above)")

    logger.info("=== E2E test complete ===")


if __name__ == "__main__":
    main()
