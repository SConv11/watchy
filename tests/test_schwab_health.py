"""Tests for Schwab token-health alerts (watchy/schwab_health.py) and the kv store.

No network: monitor_schwab reads a fake position source's provenance, the notifier
is faked, and the StateStore runs against a temp sqlite db.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from watchy.config import WatchyConfig
from watchy.state import StateStore
from watchy import schwab_health as sh


class _FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, message: str) -> bool:
        self.sent.append(message)
        return True


class _Source:
    """Stand-in position source exposing only provenance()."""

    def __init__(self, prov):
        self._prov = prov

    def provenance(self):
        return self._prov


# Fixed reference clock so weekday-based (Friday reminder) and age-based (expiry)
# logic is deterministic regardless of when the suite runs.
NOW = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc)   # a Tuesday
FRIDAY = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)  # a Friday


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    """Freeze the module clock to NOW (a Tuesday) by default; Friday tests override."""
    monkeypatch.setattr(sh, "_utcnow", lambda: NOW)


@pytest.fixture
def store(tmp_path):
    s = StateStore(db_path=str(tmp_path / "state.db"))
    yield s
    s.close()


def _cfg(enabled=True) -> WatchyConfig:
    c = WatchyConfig()
    c.schwab.enabled = enabled
    return c


# --- kv store ---

def test_kv_roundtrip_and_missing(store):
    assert store.get_kv("nope") is None
    store.set_kv("k", "v1")
    assert store.get_kv("k") == "v1"
    store.set_kv("k", "v2")  # upsert
    assert store.get_kv("k") == "v2"


def test_record_auth_success_sets_clock_and_clears_warning(store):
    store.set_kv(sh.KV_EXPIRY_WARNED_AT, "stale")
    sh.record_auth_success(store)
    assert store.get_kv(sh.KV_AUTH_AT)  # an ISO timestamp
    assert store.get_kv(sh.KV_EXPIRY_WARNED_AT) == ""  # cleared for the new cycle


# --- monitor_schwab: disabled ---

def test_monitor_disabled_is_noop(store):
    note = _FakeNotifier()
    sh.monitor_schwab(_cfg(enabled=False), store, note, _Source("Schwab cache (3d old)"))
    assert note.sent == []


# --- monitor_schwab: non-live snapshot → re-auth alert (deduped per day) ---

def test_monitor_fallback_alerts_once_per_day(store):
    note = _FakeNotifier()
    src = _Source("Schwab cache, as of ... (3d old)")

    sh.monitor_schwab(_cfg(), store, note, src)
    assert len(note.sent) == 1
    assert "re-auth needed" in note.sent[0].lower()

    # Same day → suppressed.
    sh.monitor_schwab(_cfg(), store, note, src)
    assert len(note.sent) == 1


def test_monitor_no_data_at_all_alerts(store):
    note = _FakeNotifier()
    sh.monitor_schwab(_cfg(), store, note, _Source(None))
    assert len(note.sent) == 1
    assert "re-auth needed" in note.sent[0].lower()


def test_monitor_live_is_silent(store):
    note = _FakeNotifier()
    sh.monitor_schwab(_cfg(), store, note, _Source("Schwab (live)"))
    assert note.sent == []


# --- monitor_schwab: live OK but token aging → expiry warning (deduped per cycle) ---

def test_monitor_expiry_soon_warns_once_per_cycle(store):
    note = _FakeNotifier()
    live = _Source("Schwab (live)")
    old = (NOW - timedelta(days=6, hours=12)).isoformat()
    store.set_kv(sh.KV_AUTH_AT, old)

    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 1
    assert "schwab token" in note.sent[0].lower()
    assert "~1 day" in note.sent[0].lower()  # ~0.5 days left → most-urgent tier

    # Same auth cycle, same tier → no repeat.
    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 1

    # A fresh auth resets the marker → a later aging warning is allowed again.
    sh.record_auth_success(store)
    store.set_kv(sh.KV_AUTH_AT, old)  # pretend it aged again
    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 2


def test_monitor_expiry_escalates_two_day_then_one_day(store):
    note = _FakeNotifier()
    live = _Source("Schwab (live)")

    # ~1.5 days left (5.5 days old) → the ≤2-day stage fires first.
    store.set_kv(sh.KV_AUTH_AT, (NOW - timedelta(days=5, hours=12)).isoformat())
    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 1
    assert "~2 days" in note.sent[0].lower()

    # Re-check at the same ≤2-day stage → suppressed.
    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 1

    # ~0.5 days left (6.5 days old) → escalates to the ≤1-day stage despite the prior warning.
    store.set_kv(sh.KV_AUTH_AT, (NOW - timedelta(days=6, hours=12)).isoformat())
    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 2
    assert "~1 day" in note.sent[1].lower()

    # ≤1-day stage again → suppressed (already at the most-urgent tier).
    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 2


def test_monitor_expiry_three_day_stage_warns(store):
    note = _FakeNotifier()
    # ~2.5 days left (4.5 days old) → the ≤3-day stage fires (yellow, "~3 days").
    store.set_kv(sh.KV_AUTH_AT, (NOW - timedelta(days=4, hours=12)).isoformat())
    sh.monitor_schwab(_cfg(), store, note, _Source("Schwab (live)"))
    assert len(note.sent) == 1
    assert "~3 days" in note.sent[0].lower()
    assert "🟡" in note.sent[0]


def test_monitor_expiry_silent_above_three_days(store):
    note = _FakeNotifier()
    # ~3.5 days left (3.5 days old) → outside all warning windows.
    store.set_kv(sh.KV_AUTH_AT, (NOW - timedelta(days=3, hours=12)).isoformat())
    sh.monitor_schwab(_cfg(), store, note, _Source("Schwab (live)"))
    assert note.sent == []


def test_monitor_live_and_fresh_is_silent(store):
    note = _FakeNotifier()
    store.set_kv(sh.KV_AUTH_AT, NOW.isoformat())
    sh.monitor_schwab(_cfg(), store, note, _Source("Schwab (live)"))
    assert note.sent == []


def test_monitor_live_no_recorded_auth_is_silent(store):
    note = _FakeNotifier()
    sh.monitor_schwab(_cfg(), store, note, _Source("Schwab (live)"))  # no KV_AUTH_AT
    assert note.sent == []


# --- monitor_schwab: Friday proactive re-auth reminder (deduped per UTC Friday) ---

def test_monitor_friday_reminds_once_per_day(store, monkeypatch):
    monkeypatch.setattr(sh, "_utcnow", lambda: FRIDAY)
    note = _FakeNotifier()
    live = _Source("Schwab (live)")  # token fresh (no KV_AUTH_AT) → only the reminder

    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 1
    assert "friday re-auth" in note.sent[0].lower()

    # Same Friday → suppressed.
    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 1


def test_monitor_no_friday_reminder_on_other_days(store):
    note = _FakeNotifier()  # frozen_now → Tuesday
    sh.monitor_schwab(_cfg(), store, note, _Source("Schwab (live)"))
    assert note.sent == []


def test_monitor_friday_reminder_skipped_when_not_live(store, monkeypatch):
    """A dead token on a Friday gets the louder re-auth alert, not the Friday nudge."""
    monkeypatch.setattr(sh, "_utcnow", lambda: FRIDAY)
    note = _FakeNotifier()
    sh.monitor_schwab(_cfg(), store, note, _Source("Schwab cache (3d old)"))
    assert len(note.sent) == 1
    assert "re-auth needed" in note.sent[0].lower()
    assert "friday re-auth" not in note.sent[0].lower()
