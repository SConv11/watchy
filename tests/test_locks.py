"""Tests for the per-ticker lock registry (#9)."""

import threading

from watchy.locks import TickerLockRegistry


class TestTickerLockRegistry:
    def test_same_ticker_same_lock(self):
        reg = TickerLockRegistry()
        assert reg.get("NVDA") is reg.get("NVDA")

    def test_case_insensitive(self):
        reg = TickerLockRegistry()
        assert reg.get("nvda") is reg.get("NVDA")

    def test_different_tickers_different_locks(self):
        reg = TickerLockRegistry()
        assert reg.get("NVDA") is not reg.get("TSLA")

    def test_lock_is_usable_mutex(self):
        reg = TickerLockRegistry()
        lock = reg.get("NVDA")
        with lock:
            assert lock.locked()
        assert not lock.locked()

    def test_concurrent_get_returns_one_lock(self):
        """Many threads racing to first-create the same ticker get the same lock."""
        reg = TickerLockRegistry()
        seen: list = []
        barrier = threading.Barrier(20)

        def grab():
            barrier.wait()
            seen.append(reg.get("AMD"))

        threads = [threading.Thread(target=grab) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(id(x) for x in seen)) == 1
