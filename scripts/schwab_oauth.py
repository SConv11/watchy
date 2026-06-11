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

Re-auth (every ~7 days): the Schwab refresh token expires after 7 days, and a plain
re-run only refreshes the *access* token from the still-valid refresh token — it does
NOT reset the 7-day clock or start a fresh OAuth. To force a brand-new refresh token,
pass --force: it moves the existing token db aside, runs the full browser OAuth, and on
success deletes the backup (on failure it restores the backup, so a still-valid token is
never lost).

Usage:
    python scripts/schwab_oauth.py            # reuse/refresh if a token db exists
    python scripts/schwab_oauth.py --force    # force a fresh full OAuth (weekly re-auth)
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watchy.config import load_config  # noqa: E402
from watchy.schwab import SchwabClient  # noqa: E402


def _restore_backup(stashed: bool, backup_path: str, tokens_path: str) -> None:
    """Put a --force-stashed token db back if the fresh OAuth didn't succeed."""
    if not stashed:
        return
    # A failed flow may still have written a partial db; the stashed one is known-good.
    if os.path.exists(tokens_path):
        os.remove(tokens_path)
    if os.path.exists(backup_path):
        os.rename(backup_path, tokens_path)
        print(f"Restored previous token db from {backup_path}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time / weekly Schwab OAuth helper.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force a fresh full OAuth: move the existing token db aside so schwabdev "
        "re-runs the browser flow (issues a new 7-day refresh token). Restored on failure.",
    )
    args = parser.parse_args()

    config = load_config()
    sc = config.schwab

    if not (sc.api_key and sc.api_secret):
        print("ERROR: schwab.api_key / api_secret are empty in ~/watchy_config/secrets.yaml")
        return 2

    tokens_path = os.path.expanduser(sc.tokens_path)
    print(f"callback_url : {sc.callback_url}")
    print(f"tokens_path  : {tokens_path}")

    # --force: stash the existing token db so schwabdev sees no valid tokens and does
    # the full browser OAuth (a plain refresh would NOT reset the 7-day clock). Restore
    # it if auth fails so we never throw away a token that's still usable.
    backup_path = tokens_path + ".bak"
    stashed = False
    if args.force and os.path.exists(tokens_path):
        if os.path.exists(backup_path):
            os.remove(backup_path)
        os.rename(tokens_path, backup_path)
        stashed = True
        print(f"--force: moved token db aside → {backup_path}; starting fresh OAuth.")
    elif os.path.exists(tokens_path):
        print("Token file exists — will refresh/reuse, no browser needed. "
              "(Pass --force for a fresh 7-day token.)")
    else:
        print("No token file — first-run OAuth will start; follow the printed URL.")

    try:
        import schwabdev  # noqa: F401
    except ImportError:
        print("ERROR: schwabdev not installed in this env — `pip install schwabdev`")
        _restore_backup(stashed, backup_path, tokens_path)
        return 2

    # SchwabClient.get_account_summary() lazily builds the schwabdev.Client (which
    # runs OAuth if needed) and performs a real read. enabled must be True for the
    # client to be 'ready'; this tool is explicitly for doing the auth, so force it.
    sc.enabled = True
    client = SchwabClient(sc)
    try:
        summary = client.get_account_summary()
    except Exception as exc:  # noqa: BLE001 — restore the stashed token before bailing
        print(f"\nFAILED: OAuth/API error: {exc}")
        _restore_backup(stashed, backup_path, tokens_path)
        return 1

    if summary is None:
        print("\nFAILED: no account summary returned (auth or API error). "
              "Check the logs above; re-run after fixing.")
        _restore_backup(stashed, backup_path, tokens_path)
        return 1

    # Auth succeeded — the fresh token db is good; drop the stale backup.
    if stashed and os.path.exists(backup_path):
        os.remove(backup_path)

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
