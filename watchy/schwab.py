"""Schwab API client — the live position backend (via ``schwabdev``).

This is the *live* layer of the position source. Schwab's OAuth needs a 7-day
refresh-token reauth that's hostile to an unattended daemon, so robustness
(caching the last good fetch, falling back to it, then to a manual file) lives in
``RobustPositionSource`` — this client only talks to the API and is deliberately
fail-loud-then-degrade: any API/auth failure raises out of ``_fetch_*`` and is
turned into ``None`` by the public getters, which is the signal the composite uses
to fall back to the cache / manual file.

Setup (one-time, on the box that runs the daemon):
  1. Register an app at https://developer.schwab.com/ — note the app key/secret
     and set the callback URL (default https://127.0.0.1).
  2. Put key/secret into ``~/watchy_config/secrets.yaml`` under ``schwab:`` and set
     ``enabled: true``.
  3. First run does a browser OAuth; schwabdev prints a URL — authorise, then paste
     the redirect URL back into the terminal. Tokens persist to ``tokens_path``.

Package: https://github.com/tylerebowers/Schwab-API-Python  (``pip install schwabdev``)
"""

from __future__ import annotations

import logging
import os

from watchy.config import SchwabConfig
from watchy.positions import AccountSummary, Position, PositionSource

logger = logging.getLogger(__name__)


def _f(value: object) -> float | None:
    """Best-effort float coercion; None on missing/non-numeric."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class SchwabClient(PositionSource):
    """Schwab brokerage API client (read-only: positions + balances).

    When ``SchwabConfig.enabled`` is False (or schwabdev isn't installed / OAuth
    hasn't been done), the getters return empty/None — safe to call, no crash —
    so the composite degrades to cache/file. ``get_account_summary`` returning
    None is exactly that fallback signal; it returns an ``AccountSummary`` only on
    a genuine successful fetch.
    """

    def __init__(self, config: SchwabConfig) -> None:
        self.config = config
        self._ready = bool(config.enabled and config.api_key and config.api_secret)
        self._client = None  # lazily constructed schwabdev.Client
        self._client_failed = False
        if not self._ready:
            logger.info("Schwab integration not configured — position data unavailable")

    # --- public PositionSource interface ---

    def get_position(self, ticker: str) -> Position | None:
        if not self._ready:
            return None
        try:
            summary = self._fetch_account_summary()
        except Exception:
            logger.exception("Failed to fetch Schwab position for %s", ticker)
            return None
        if summary is None:
            return None
        t = ticker.upper()
        for pos in summary.positions:
            if pos.ticker.upper() == t:
                return pos
        return None

    def get_all_positions(self) -> list[Position]:
        if not self._ready:
            return []
        try:
            summary = self._fetch_account_summary()
        except Exception:
            logger.exception("Failed to fetch Schwab positions")
            return []
        return list(summary.positions) if summary else []

    def get_account_summary(self) -> AccountSummary | None:
        if not self._ready:
            return None
        try:
            return self._fetch_account_summary()
        except Exception:
            logger.exception("Failed to fetch Schwab account summary")
            return None

    # --- schwabdev plumbing ---

    def _get_client(self):
        """Return a cached schwabdev.Client, or None if it can't be created."""
        if self._client is not None:
            return self._client
        if self._client_failed:
            return None
        try:
            import schwabdev
        except ImportError:
            logger.error("schwabdev not installed — run `pip install schwabdev`")
            self._client_failed = True
            return None
        try:
            self._client = schwabdev.Client(
                self.config.api_key,
                self.config.api_secret,
                self.config.callback_url,
                tokens_file=os.path.expanduser(self.config.tokens_path),
            )
        except Exception:
            # e.g. expired refresh token needing manual reauth → degrade to fallback.
            logger.exception("Failed to initialise Schwab client (re-auth may be needed)")
            self._client_failed = True
            return None
        return self._client

    def _account_hash(self, client) -> str:
        """Resolve the account hash for config.account_id (or the first account)."""
        resp = client.account_linked()
        resp.raise_for_status()
        accounts = resp.json() or []
        if not accounts:
            raise RuntimeError("No linked Schwab accounts")
        wanted = str(self.config.account_id).strip()
        if wanted:
            for acct in accounts:
                if str(acct.get("accountNumber")) == wanted:
                    return acct["hashValue"]
            raise RuntimeError(f"Schwab account_id {wanted!r} not among linked accounts")
        return accounts[0]["hashValue"]

    def _fetch_account_summary(self) -> AccountSummary | None:
        """Fetch positions + balances. Raises on API/auth failure; None if no client."""
        client = self._get_client()
        if client is None:
            return None

        acct_hash = self._account_hash(client)
        resp = client.account_details(acct_hash, fields="positions")
        resp.raise_for_status()
        sec = (resp.json() or {}).get("securitiesAccount", {})

        positions = [
            self._to_position(p) for p in sec.get("positions", [])
            if p.get("instrument", {}).get("symbol")
        ]
        balances = sec.get("currentBalances", {})
        total = _f(balances.get("liquidationValue"))
        if total is None:
            total = sum(p.market_value for p in positions if p.market_value is not None)

        return AccountSummary(
            account_id=str(sec.get("accountNumber") or self.config.account_id or "schwab"),
            total_value=total,
            buying_power=_f(balances.get("buyingPower")),
            cash_balance=_f(balances.get("cashBalance")),
            positions=positions,
        )

    @staticmethod
    def _to_position(p: dict) -> Position:
        """Map a Schwab position payload to a Watchy Position."""
        symbol = str(p.get("instrument", {}).get("symbol", "")).upper()
        qty = (_f(p.get("longQuantity")) or 0.0) - (_f(p.get("shortQuantity")) or 0.0)
        avg = _f(p.get("averagePrice")) or 0.0
        market_value = _f(p.get("marketValue"))
        # Schwab exposes a few P&L fields; prefer the open (unrealized) figure.
        unrealized = _f(p.get("longOpenProfitLoss"))
        if unrealized is None:
            unrealized = _f(p.get("currentDayProfitLoss"))

        pos = Position(
            ticker=symbol,
            quantity=qty,
            average_cost=avg,
            market_value=market_value,
            unrealized_pnl=unrealized,
            current_price=(market_value / qty) if (market_value is not None and qty) else None,
        )
        cost_basis = avg * qty
        if unrealized is not None and cost_basis:
            pos.unrealized_pnl_pct = unrealized / cost_basis * 100.0
        return pos
