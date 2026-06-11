"""Schwab token-health monitoring: proactive expiry warnings + re-auth alerts.

The Schwab refresh token is valid only ~7 days, after which live position fetches
silently fail and Watchy degrades to cached/manual data (see RobustPositionSource).
Left alone, that degradation is invisible — you'd act on stale holdings without
knowing. This module turns it into Telegram alerts, piggy-backing on the position
fetch a scan already does (no extra API call):

  * record_auth_success() — call right after a successful OAuth
    (scripts/schwab_oauth.py) to stamp when the 7-day clock started.
  * monitor_schwab(source) — inspect the snapshot a scan just resolved: if it
    isn't live (token expired / API down → serving cache/manual), alert that
    re-auth is needed; if it is live but the recorded auth is within ~1 day of the
    7-day limit, warn to re-auth soon. Called once per Tier 2 batch (on the shared
    source) and on each Tier 1 fired-signal scan. Deduped to one re-auth alert per
    day and one expiry warning per auth cycle.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Schwab refresh tokens are valid 7 days. Warn in two escalating stages — once when
# ≤2 days are left, then again when ≤1 day is left — so a missed first nudge gets a
# second, more urgent one before the token actually lapses.
REFRESH_TOKEN_TTL_DAYS = 7
EXPIRY_WARN_DAYS_LEFT = (2, 1)  # days-left thresholds, least → most urgent

KV_AUTH_AT = "schwab_auth_at"                       # ISO time of the last successful OAuth
KV_REAUTH_ALERT_DATE = "schwab_reauth_alert_date"   # UTC date of last "re-auth needed" alert
KV_EXPIRY_WARNED_AT = "schwab_expiry_warned_at"     # "{auth_at}|{tier}" last warned this cycle


def record_auth_success(store) -> None:
    """Stamp 'now' as the Schwab OAuth time (starts the 7-day refresh-token clock).

    Also clears the per-cycle expiry-warning marker so the next cycle can warn again.
    """
    store.set_kv(KV_AUTH_AT, datetime.now(timezone.utc).isoformat())
    store.set_kv(KV_EXPIRY_WARNED_AT, "")


def monitor_schwab(config, store, notifier, position_source) -> None:
    """Check Schwab health from the snapshot a scan already resolved (no extra fetch).

    The position source memoizes its snapshot, so reading ``provenance()`` reuses
    the fetch the scan performed rather than triggering a new one.
    """
    if not config.schwab.enabled:
        return
    prov = getattr(position_source, "provenance", lambda: None)()
    if prov != "Schwab (live)":
        # Live fetch didn't win — token likely expired / API down; we're on cache/manual.
        logger.info("Schwab enabled but scan used non-live positions (%s) — alerting", prov)
        _alert_reauth(store, notifier)
        return
    _maybe_warn_expiry(store, notifier)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _alert_reauth(store, notifier) -> None:
    """Send a 'Schwab re-auth needed' alert, at most once per UTC day."""
    if store.get_kv(KV_REAUTH_ALERT_DATE) == _today():
        return
    notifier.send(
        "🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨\n"
        "<b>🔑 SCHWAB RE-AUTH NEEDED</b>\n"
        "🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨\n"
        "Live position fetch is failing — the 7-day refresh token has likely "
        "expired. Watchy is serving cached/manual positions until you re-auth.\n"
        "<b>Fix:</b> run <code>scripts/schwab_oauth.py --force</code> on the VPS."
    )
    store.set_kv(KV_REAUTH_ALERT_DATE, _today())


def _maybe_warn_expiry(store, notifier) -> None:
    """Warn as the refresh token nears its 7-day limit.

    Two escalating stages (≤2 days left, then ≤1 day left), each sent at most once
    per auth cycle. The dedup marker records the most-urgent tier already warned, so
    a later, more-urgent stage still fires while repeats of the same stage don't.
    """
    auth_at_raw = store.get_kv(KV_AUTH_AT)
    if not auth_at_raw:
        return  # no recorded auth time — set on the next OAuth via the helper script
    try:
        auth_at = datetime.fromisoformat(auth_at_raw)
    except ValueError:
        logger.warning("Unparseable %s: %r", KV_AUTH_AT, auth_at_raw)
        return

    age_days = (datetime.now(timezone.utc) - auth_at).total_seconds() / 86400
    remaining = REFRESH_TOKEN_TTL_DAYS - age_days

    # Most urgent (smallest) days-left threshold we've crossed; None if still far off.
    tier = next((d for d in sorted(EXPIRY_WARN_DAYS_LEFT) if remaining <= d), None)
    if tier is None:
        return

    # Dedup with escalation: skip only if we've already warned this cycle at this
    # tier or a more-urgent (smaller) one.
    prev_auth, _, prev_tier = (store.get_kv(KV_EXPIRY_WARNED_AT) or "").partition("|")
    if prev_auth == auth_at_raw and prev_tier.isdigit() and int(prev_tier) <= tier:
        return

    notifier.send(_expiry_message(age_days, remaining, tier))
    store.set_kv(KV_EXPIRY_WARNED_AT, f"{auth_at_raw}|{tier}")


def _expiry_message(age_days: float, remaining: float, tier: int) -> str:
    """Build a deliberately loud, bordered alert that stands out from position advice."""
    border = "🔴" * 10 if tier <= 1 else "🟠" * 10
    when = "EXPIRES IN ~1 DAY" if tier <= 1 else "EXPIRES IN ~2 DAYS"
    return (
        f"{border}\n"
        f"<b>🔑 SCHWAB TOKEN — {when}</b>\n"
        f"{border}\n"
        f"Refresh token is ~{age_days:.1f} days old (7-day limit, "
        f"~{max(remaining, 0):.1f} days left).\n"
        "<b>Re-auth now</b> or live positions go stale:\n"
        "run <code>scripts/schwab_oauth.py --force</code> on the VPS."
    )
