"""Shared US-equity (XNYS) trading-calendar helpers.

Centralises the exchange_calendars access used by the daemon's market-hours
guard, the Tier 2 trading-day guard, and the weekly full-risk-day predicate so
they all load one calendar and degrade to the same weekday fallbacks together.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("watchy.market_calendar")

_calendar = None
_calendar_failed = False


def get_calendar():
    """Lazily load the XNYS exchange calendar, or None if it can't be loaded.

    exchange_calendars ships with yfinance-cache, so it's normally present; if
    the import ever fails we cache the failure and callers fall back to plain
    weekday checks (holiday-blind, but never crash).
    """
    global _calendar, _calendar_failed
    if _calendar_failed:
        return None
    if _calendar is None:
        try:
            import exchange_calendars as xcals
            _calendar = xcals.get_calendar("XNYS")
        except Exception:
            logger.warning(
                "exchange_calendars unavailable; using weekday fallbacks",
                exc_info=True,
            )
            _calendar_failed = True
            return None
    return _calendar


def is_trading_day(now: datetime | None = None) -> bool:
    """True if ``now``'s date is a regular US equity trading session.

    Falls back to Mon–Fri (holiday-blind) if the calendar can't be loaded.
    """
    now = now or datetime.now(timezone.utc)
    cal = get_calendar()
    if cal is not None:
        try:
            import pandas as pd
            return bool(cal.is_session(pd.Timestamp(now.date())))
        except Exception:
            logger.warning("is_session check failed; weekday fallback", exc_info=True)
    return now.weekday() < 5  # Mon–Fri


def is_weekly_full_risk_day(now: datetime | None = None) -> bool:
    """True on the **first trading session of the (Mon–Sun) week**.

    This is the day Tier 2 escalates to the full 3-way risk debate and bypasses
    the proximity gate, so every ticker gets one guaranteed full-risk run per
    week. Keying off "first session of the week" (rather than literally Monday)
    keeps that weekly guarantee even when Monday is a market holiday — the run
    shifts to Tuesday. Falls back to Monday (weekday 0) if the calendar can't be
    loaded.
    """
    now = now or datetime.now(timezone.utc)
    cal = get_calendar()
    if cal is None:
        return now.weekday() == 0  # fallback: Monday
    try:
        import pandas as pd
        d = pd.Timestamp(now.date())
        if not cal.is_session(d):
            return False
        prev = cal.previous_session(d)
        # First session of the week iff the previous session is in a prior
        # ISO week (ISO weeks start Monday, matching our Mon–Sun grouping).
        return (prev.isocalendar()[0], prev.isocalendar()[1]) != (
            d.isocalendar()[0], d.isocalendar()[1]
        )
    except Exception:
        logger.warning("weekly-full-risk-day check failed; Monday fallback", exc_info=True)
        return now.weekday() == 0
