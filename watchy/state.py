"""SQLite state store for crossover detection, cooldown, and run history."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = os.path.expanduser("~/watchy/state.db")


def _ensure_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


class StateStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        _ensure_dir(db_path)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS ticker_state (
                ticker TEXT PRIMARY KEY,
                prev_sma_50_above_200 INTEGER,       -- bool: previous MA relationship
                prev_macd_above_signal INTEGER,       -- bool: previous MACD relationship
                prev_rsi REAL,                         -- last RSI value
                prev_atr REAL,                         -- last ATR value
                avg_volume_20d REAL,                   -- 20-day average volume
                avg_atr_20d REAL,                      -- 20-day average ATR
                last_full_analysis_ts TEXT,            -- ISO timestamp of last Tier 2 run
                updated_ts TEXT                        -- last update timestamp
            );

            CREATE TABLE IF NOT EXISTS signal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                fired_ts TEXT NOT NULL,
                details TEXT,                           -- JSON with signal context
                notified INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS run_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                tier TEXT NOT NULL,                     -- 'tier1' or 'tier2'
                trigger_type TEXT,                      -- signal type or 'scheduled'
                started_ts TEXT NOT NULL,
                completed_ts TEXT,
                success INTEGER DEFAULT 0,
                summary TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_signal_log_ticker
                ON signal_log(ticker, signal_type);
            CREATE INDEX IF NOT EXISTS idx_signal_log_fired
                ON signal_log(fired_ts);
            CREATE INDEX IF NOT EXISTS idx_run_history_ticker
                ON run_history(ticker, started_ts);
        """)
        self._conn.commit()

    # --- ticker state ---

    def get_ticker_state(self, ticker: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM ticker_state WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
        if row is None:
            return {}
        cols = [d[0] for d in self._conn.execute(
            "SELECT * FROM ticker_state LIMIT 0"
        ).description]
        return dict(zip(cols, row))

    def save_ticker_state(self, ticker: str, **kwargs: Any) -> None:
        kwargs.setdefault("updated_ts", _now_iso())
        columns = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [ticker.upper()]
        self._conn.execute(
            f"INSERT INTO ticker_state (ticker, {', '.join(kwargs)}) "
            f"VALUES (?, {', '.join('?' for _ in kwargs)}) "
            f"ON CONFLICT(ticker) DO UPDATE SET {columns}",
            [ticker.upper()] + values,
        )
        self._conn.commit()

    # --- signal cooldown ---

    def is_in_cooldown(self, ticker: str, signal_type: str, cooldown_hours: float) -> bool:
        since = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat()
        row = self._conn.execute(
            "SELECT 1 FROM signal_log WHERE ticker = ? AND signal_type = ? "
            "AND fired_ts > ? LIMIT 1",
            (ticker.upper(), signal_type, since),
        ).fetchone()
        return row is not None

    def log_signal(self, ticker: str, signal_type: str, details: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO signal_log (ticker, signal_type, fired_ts, details) "
            "VALUES (?, ?, ?, ?)",
            (
                ticker.upper(),
                signal_type,
                _now_iso(),
                json.dumps(details) if details else None,
            ),
        )
        self._conn.commit()

    def mark_notified(self, ticker: str, signal_type: str) -> None:
        self._conn.execute(
            "UPDATE signal_log SET notified = 1 "
            "WHERE ticker = ? AND signal_type = ? AND notified = 0",
            (ticker.upper(), signal_type),
        )
        self._conn.commit()

    # --- run history ---

    def start_run(self, ticker: str, tier: str, trigger_type: str = "scheduled") -> int:
        cur = self._conn.execute(
            "INSERT INTO run_history (ticker, tier, trigger_type, started_ts) "
            "VALUES (?, ?, ?, ?)",
            (ticker.upper(), tier, trigger_type, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid

    def complete_run(self, run_id: int, success: bool, summary: str = "") -> None:
        self._conn.execute(
            "UPDATE run_history SET completed_ts = ?, success = ?, summary = ? "
            "WHERE id = ?",
            (_now_iso(), int(success), summary, run_id),
        )
        self._conn.commit()

    # --- housekeeping ---

    def close(self) -> None:
        self._conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
