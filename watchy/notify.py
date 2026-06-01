"""Telegram Bot notifications for Watchy.

Pushes natural-language summaries on: signal fired, pipeline result, errors.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)
        if not self._enabled:
            logger.warning("Telegram not configured — notifications disabled")

    def send(self, message: str) -> bool:
        """Send a plain text message. Returns True on success."""
        if not self._enabled:
            logger.info("[telegram would send]: %s", message)
            return False
        return self._post("sendMessage", {"text": message, "parse_mode": "HTML"})

    def signal_fired(
        self,
        ticker: str,
        signal_type: str,
        indicators: dict[str, Any],
        triggered_analysts: list[str],
    ) -> bool:
        """Notify that a technical signal has fired."""
        label = _signal_label(signal_type)
        price = indicators.get("current_price", "N/A")
        rsi = indicators.get("rsi", "N/A")
        stage = indicators.get("sepa_stage", "?")

        lines = [
            f"<b>Signal Fired</b> — ${ticker}",
            f"<b>Signal:</b> {label}",
            f"<b>Price:</b> ${price}",
            f"<b>RSI:</b> {rsi}",
            f"<b>SEPA Stage:</b> {_stage_name(stage)}",
        ]
        if triggered_analysts:
            lines.append(f"<b>Analysts launching:</b> {', '.join(triggered_analysts)}")

        return self.send("\n".join(lines))

    def pipeline_result(
        self,
        ticker: str,
        signal_type: str,
        result: dict[str, Any],
        *,
        position_text: str | None = None,
        advice: dict[str, Any] | None = None,
    ) -> bool:
        """Notify with a natural-language pipeline summary.

        If position_text and advice are provided, includes position context and
        a specific recommendation on whether to alter the position.
        """
        recs = result.get("recommendations", [])
        rec_text = ", ".join(recs) if recs else "no actionable recommendation"
        risk = result.get("risk_assessment") or "not assessed"
        summary = result.get("summary", "")

        lines = [
            f"<b>Analysis Complete</b> — ${ticker}",
            f"<b>Trigger:</b> {_signal_label(signal_type)}",
            f"<b>Recommendation:</b> {rec_text}",
            f"<b>Risk:</b> {risk}",
        ]
        if summary:
            lines.append(f"<b>Summary:</b> {summary}")

        # position context
        if position_text:
            lines.append("")
            lines.append(f"<b>Your Position:</b>\n{position_text}")

        # advisor synthesis
        if advice:
            action = advice.get("action", "?").upper()
            reasoning = advice.get("reasoning", "")
            urgency = advice.get("urgency", "")
            suggested = advice.get("suggested_size", "")
            risk_note = advice.get("risk_note", "")

            urgency_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(urgency, "")
            lines.append("")
            lines.append(f"<b>Position Advice:</b> {urgency_icon} <b>{action}</b> ({urgency} urgency)")
            if reasoning:
                lines.append(f"<i>{reasoning}</i>")
            if suggested:
                lines.append(f"<b>Suggested size:</b> {suggested}")
            if risk_note:
                lines.append(f"<b>Key risk:</b> {risk_note}")

        return self.send("\n".join(lines))

    def error(self, context: str, error: Exception) -> bool:
        """Notify on critical errors."""
        return self.send(
            f"<b>⚠ Watchy Error</b>\n"
            f"<b>Context:</b> {context}\n"
            f"<b>Error:</b> {type(error).__name__}: {error}"
        )

    def _post(self, method: str, payload: dict[str, Any]) -> bool:
        try:
            import urllib.request
            import json

            url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                if not body.get("ok"):
                    logger.error("Telegram API error: %s", body)
                    return False
                return True
        except Exception:
            logger.exception("Failed to send Telegram message")
            return False


def _signal_label(signal_type: str) -> str:
    labels: dict[str, str] = {
        "golden_cross": "Golden Cross (50MA ↑ 200MA)",
        "death_cross": "Death Cross (50MA ↓ 200MA)",
        "rsi_oversold": "RSI Oversold (< 30)",
        "rsi_overbought": "RSI Overbought (> 70)",
        "macd_bullish_cross": "MACD Bullish Crossover",
        "macd_bearish_cross": "MACD Bearish Crossover",
        "bollinger_upper_breach": "Bollinger Upper Band Breach",
        "bollinger_lower_breach": "Bollinger Lower Band Breach",
        "volume_anomaly_strong": "Volume Anomaly (≥ 2x avg)",
        "volume_anomaly_moderate": "Volume Anomaly (≥ 1.5x avg)",
        "atr_spike": "ATR Spike (≥ 1.5x avg)",
        "scheduled_daily": "Scheduled Daily Run",
    }
    return labels.get(signal_type, signal_type)


def _stage_name(stage: int | None) -> str:
    names = {1: "Basing", 2: "Advancing", 3: "Topping", 4: "Declining"}
    return names.get(stage, "?") if stage is not None else "?"
