#!/usr/bin/env python
"""One-time Schwab OAuth + connectivity check.

Run this on the box that runs the daemon (the VPS), with the `trading` pyenv,
*after* the Schwab app is "Ready For Use" and api_key/api_secret/callback_url are
set in ~/watchy_config/secrets.yaml under `schwab:`.

What it does:
  1. Loads Watchy config (merging secrets.yaml).
  2. Constructs the schwabdev client — on first run with no token file this kicks
     off the browser OAuth: schwabdev prints an auth URL; open it, log in, approve,
     then paste the full https://127.0.0.1... redirect URL back into the terminal.
     Tokens are written to schwab.tokens_path (a schwabdev 3.x SQLite db,
     default ~/watchy_config/schwab_tokens.db).
  3. Does a real read (account summary) to confirm the credentials work, and prints
     a redacted summary. No orders, no writes — read-only.

The browser need not be on the VPS: 127.0.0.1 won't actually serve anything, you're
only copying the redirected URL out of the address bar. So open the printed URL in
your local browser, then paste the resulting URL string back into the VPS terminal.

Usage:
    python scripts/schwab_oauth.py
"""

from __future__ import annotations

import os
import sys

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watchy.config import load_config  # noqa: E402
from watchy.schwab import SchwabClient  # noqa: E402


def main() -> int:
    config = load_config()
    sc = config.schwab

    if not (sc.api_key and sc.api_secret):
        print("ERROR: schwab.api_key / api_secret are empty in ~/watchy_config/secrets.yaml")
        return 2

    tokens_path = os.path.expanduser(sc.tokens_path)
    print(f"callback_url : {sc.callback_url}")
    print(f"tokens_path  : {tokens_path}")
    print(
        "Token file exists — will refresh/reuse, no browser needed."
        if os.path.exists(tokens_path)
        else "No token file — first-run OAuth will start; follow the printed URL."
    )

    try:
        import schwabdev  # noqa: F401
    except ImportError:
        print("ERROR: schwabdev not installed in this env — `pip install schwabdev`")
        return 2

    # SchwabClient.get_account_summary() lazily builds the schwabdev.Client (which
    # runs OAuth if needed) and performs a real read. enabled must be True for the
    # client to be 'ready'; this tool is explicitly for doing the auth, so force it.
    sc.enabled = True
    client = SchwabClient(sc)
    summary = client.get_account_summary()

    if summary is None:
        print("\nFAILED: no account summary returned (auth or API error). "
              "Check the logs above; re-run after fixing.")
        return 1

    # Stamp the auth time so the daemon's daily health check can warn ~1 day before
    # the 7-day refresh token expires (see watchy/schwab_health.py).
    try:
        from watchy.schwab_health import record_auth_success
        from watchy.state import StateStore

        store = StateStore()
        record_auth_success(store)
        store.close()
        print("Recorded auth time for the 7-day expiry tracker.")
    except Exception as exc:  # noqa: BLE001 — non-fatal; auth itself succeeded
        print(f"(warning: couldn't record auth time for expiry tracking: {exc})")

    print("\nOK — Schwab connected. Token file written to:", tokens_path)
    print(f"  account_id   : {summary.account_id}")
    print(f"  total_value  : {summary.total_value}")
    print(f"  cash_balance : {summary.cash_balance}")
    print(f"  positions    : {len(summary.positions)}")
    for p in summary.positions:
        print(f"    - {p.ticker}: qty={p.quantity} avg={p.average_cost} mv={p.market_value}")
    print("\nNote: the refresh token expires in ~7 days; re-run this then.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
