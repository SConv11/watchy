"""Schwab API client for position and account data.

Currently a stub — returns empty/None values when SchwabConfig.enabled is False.
When enabled with valid credentials, this will call the Schwab REST API to fetch
real positions, balances, and order history.

API docs: https://developer.schwab.com/
Python SDK: https://github.com/tylerebowers/Schwab-API-Python
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from watchy.config import SchwabConfig

logger = logging.getLogger(__name__)


@dataclass
class Position:
    ticker: str
    quantity: float
    average_cost: float
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    current_price: float | None = None


@dataclass
class AccountSummary:
    account_id: str
    total_value: float
    buying_power: float
    cash_balance: float
    positions: list[Position] = field(default_factory=list)


class SchwabClient:
    """Schwab brokerage API client.

    When SchwabConfig.enabled is False (default), all methods return empty/None
    values — safe to call, no errors, just no data.

    To enable, set enabled: true and fill in api_key, api_secret, account_id in
    config.yaml, then replace the stub methods with real API calls.
    """

    def __init__(self, config: SchwabConfig) -> None:
        self.config = config
        self._ready = bool(config.enabled and config.api_key and config.api_secret)
        if not self._ready:
            logger.info("Schwab integration not configured — position data unavailable")

    def get_position(self, ticker: str) -> Position | None:
        """Return the current position for a ticker, or None if not held."""
        if not self._ready:
            return None

        try:
            return self._fetch_position(ticker.upper())
        except Exception:
            logger.exception("Failed to fetch Schwab position for %s", ticker)
            return None

    def get_all_positions(self) -> list[Position]:
        """Return all current positions."""
        if not self._ready:
            return []

        try:
            return self._fetch_all_positions()
        except Exception:
            logger.exception("Failed to fetch Schwab positions")
            return []

    def get_account_summary(self) -> AccountSummary | None:
        """Return account balances and buying power."""
        if not self._ready:
            return None

        try:
            return self._fetch_account_summary()
        except Exception:
            logger.exception("Failed to fetch Schwab account summary")
            return None

    # --- stub implementations (replace with real API calls) ---

    def _fetch_position(self, ticker: str) -> Position | None:
        """Stub — replace with:
            import schwabdev
            client = schwabdev.Client(self.config.api_key, self.config.api_secret)
            resp = client.account_details(self.config.account_id, fields="positions")
            for pos in resp.get("securitiesAccount", {}).get("positions", []):
                if pos["instrument"]["symbol"] == ticker:
                    return Position(
                        ticker=ticker,
                        quantity=pos["longQuantity"],
                        average_cost=pos["averagePrice"],
                        market_value=pos["marketValue"],
                        unrealized_pnl=pos.get("unrealizedDayPL", 0),
                    )
            return None
        """
        return None

    def _fetch_all_positions(self) -> list[Position]:
        """Stub — replace with full account positions call."""
        return []

    def _fetch_account_summary(self) -> AccountSummary | None:
        """Stub — replace with account balances call."""
        return None

    # --- helpers ---

    def format_position_context(self, ticker: str) -> str | None:
        """Return a human-readable summary of the position for LLM context.

        Returns None if no position held or Schwab not configured.
        """
        pos = self.get_position(ticker)
        if pos is None:
            return None

        lines = [
            f"Current position in {pos.ticker}:",
            f"  Shares: {pos.quantity:.0f}" if pos.quantity == int(pos.quantity)
            else f"  Shares: {pos.quantity}",
            f"  Average cost: ${pos.average_cost:.2f}",
        ]
        if pos.current_price:
            lines.append(f"  Current price: ${pos.current_price:.2f}")
        if pos.market_value:
            lines.append(f"  Market value: ${pos.market_value:,.2f}")
        if pos.unrealized_pnl is not None:
            lines.append(f"  Unrealized P&L: ${pos.unrealized_pnl:,.2f}")
        return "\n".join(lines)

    def format_portfolio_context(self) -> str | None:
        """Return a summary of total account for LLM context."""
        summary = self.get_account_summary()
        if summary is None:
            return None

        lines = [
            f"Account: {summary.account_id}",
            f"  Total value: ${summary.total_value:,.2f}",
            f"  Buying power: ${summary.buying_power:,.2f}",
            f"  Cash: ${summary.cash_balance:,.2f}",
            f"  Positions held: {len(summary.positions)}",
        ]
        return "\n".join(lines)
