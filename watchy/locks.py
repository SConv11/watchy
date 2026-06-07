"""Per-ticker locks for cross-tier mutual exclusion.

Tier 1 (hourly) and Tier 2 (daily) can fire for the same ticker at overlapping
times. Running two analyst pipelines for one ticker concurrently wastes API
budget and can interleave state writes. A `TickerLockRegistry` hands out one
lock per ticker so both tiers serialize on the same symbol while different
symbols still run in parallel.
"""

from __future__ import annotations

import threading


class TickerLockRegistry:
    """Thread-safe registry of one `threading.Lock` per ticker symbol."""

    def __init__(self) -> None:
        self._registry_lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def get(self, ticker: str) -> threading.Lock:
        """Return the lock for *ticker*, creating it on first use.

        Ticker is normalized to upper-case so "nvda" and "NVDA" share a lock.
        """
        key = ticker.upper()
        with self._registry_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock
