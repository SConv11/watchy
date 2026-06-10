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
    old = (datetime.now(timezone.utc) - timedelta(days=6, hours=12)).isoformat()
    store.set_kv(sh.KV_AUTH_AT, old)

    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 1
    assert "expiring soon" in note.sent[0].lower()

    # Same auth cycle → no repeat.
    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 1

    # A fresh auth resets the marker → a later aging warning is allowed again.
    sh.record_auth_success(store)
    store.set_kv(sh.KV_AUTH_AT, old)  # pretend it aged again
    sh.monitor_schwab(_cfg(), store, note, live)
    assert len(note.sent) == 2


def test_monitor_live_and_fresh_is_silent(store):
    note = _FakeNotifier()
    store.set_kv(sh.KV_AUTH_AT, datetime.now(timezone.utc).isoformat())
    sh.monitor_schwab(_cfg(), store, note, _Source("Schwab (live)"))
    assert note.sent == []


def test_monitor_live_no_recorded_auth_is_silent(store):
    note = _FakeNotifier()
    sh.monitor_schwab(_cfg(), store, note, _Source("Schwab (live)"))  # no KV_AUTH_AT
    assert note.sent == []
