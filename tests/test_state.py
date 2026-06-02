"""Tests for SQLite state store: CRUD, cooldown, run history."""

import os
import tempfile

import pytest

from watchy.state import StateStore


@pytest.fixture
def store():
    """Create a StateStore backed by a temporary SQLite file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = StateStore(path)
    yield s
    s.close()
    os.unlink(path)


class TestTickerState:
    def test_initial_state_is_empty(self, store):
        assert store.get_ticker_state("NVDA") == {}

    def test_save_and_retrieve(self, store):
        store.save_ticker_state("NVDA", prev_rsi=45.5, prev_sma_50_above_200=1)
        state = store.get_ticker_state("NVDA")
        assert state["prev_rsi"] == 45.5
        assert state["prev_sma_50_above_200"] == 1

    def test_update_existing(self, store):
        store.save_ticker_state("AAPL", prev_rsi=60.0)
        store.save_ticker_state("AAPL", prev_rsi=30.0)
        state = store.get_ticker_state("AAPL")
        assert state["prev_rsi"] == 30.0

    def test_ticker_case_insensitive(self, store):
        store.save_ticker_state("nvda", prev_rsi=50.0)
        assert store.get_ticker_state("NVDA")["prev_rsi"] == 50.0

    def test_multiple_tickers(self, store):
        store.save_ticker_state("A", prev_rsi=1.0)
        store.save_ticker_state("B", prev_rsi=2.0)
        assert store.get_ticker_state("A")["prev_rsi"] == 1.0
        assert store.get_ticker_state("B")["prev_rsi"] == 2.0


class TestSignalLog:
    def test_log_and_check_cooldown(self, store):
        store.log_signal("NVDA", "rsi_oversold", {"rsi": 25.0})

        # Should be in cooldown for 12 hours
        assert store.is_in_cooldown("NVDA", "rsi_oversold", 12.0) is True

        # Should NOT be in cooldown for 0 hours (already expired)
        assert store.is_in_cooldown("NVDA", "rsi_oversold", 0.0) is False

    def test_different_signal_types_are_independent(self, store):
        store.log_signal("NVDA", "rsi_oversold")
        assert store.is_in_cooldown("NVDA", "macd_bullish_cross", 24.0) is False

    def test_different_tickers_are_independent(self, store):
        store.log_signal("NVDA", "rsi_oversold")
        assert store.is_in_cooldown("TSLA", "rsi_oversold", 12.0) is False


class TestRunHistory:
    def test_start_and_complete_run(self, store):
        run_id = store.start_run("NVDA", "tier1", "rsi_oversold")
        assert isinstance(run_id, int)
        assert run_id > 0

        store.complete_run(run_id, success=True, summary="All good")
        # No error = success

    def test_run_ids_are_sequential(self, store):
        id1 = store.start_run("A", "tier1")
        id2 = store.start_run("B", "tier2")
        assert id2 > id1
