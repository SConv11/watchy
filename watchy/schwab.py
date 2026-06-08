"""Schwab API client — the live position backend (currently stubbed).

This is the *live* layer of the position source. Schwab's OAuth needs a 7-day
refresh-token reauth that's hostile to an unattended daemon, so robustness
(caching the last good fetch, falling back to it, then to a manual file) lives in
``RobustPositionSource`` — this client only talks to the API. It stays a safe
stub: every method returns empty/None until ``SchwabConfig.enabled`` is set with
real credentials and the ``_fetch_*`` methods are replaced with API calls. When
that happens, the surrounding cache/fallback keeps working unchanged.

API docs: https://developer.schwab.com/
Python SDK: https://github.com/tylerebowers/Schwab-API-Python
"""

from __future__ import annotations

import logging

from watchy.config import SchwabConfig
from watchy.positions import AccountSummary, Position, PositionSource

logger = logging.getLogger(__name__)


class SchwabClient(PositionSource):
    """Schwab brokerage API client (stub).

    When SchwabConfig.enabled is False (default), all methods return empty/None
    values — safe to call, no errors, just no data. ``get_account_summary``
    returning None is the signal the composite uses to fall back to cache/file.

    To enable, set enabled: true and fill in api_key, api_secret, account_id in
    config.yaml, then replace the stub _fetch_* methods with real API calls.
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
        """Return account balances and positions (None if unavailable/failed)."""
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
        """Stub — replace with account balances + positions call.

        Must raise on a real fetch failure (e.g. expired token) so the composite
        falls back to cache; return an AccountSummary (possibly with no positions)
        only on a genuine success.
        """
        return None
