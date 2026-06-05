# Watchy Implementation Plan

File-by-file plan for the open GitHub issues, in execution order. The project
won't be deployed until the whole backlog is done. Dependencies live in **both**
`requirements.txt` and `pyproject.toml` — update both wherever a dependency is added.

Run the full `pytest` suite as the gate at the end of each phase. After Phase 4,
run `tests/test_e2e.py` on one ticker before considering deploy.

---

## Phase 1 — P0 (small, isolated, ship first)

### #13 — Crossover signals never fire
- **`watchy/indicators.py`** → `detect_signals()`: replace the four identity checks with value checks.
  - `prev_above is False` → `prev_above == 0` (golden_cross, macd_bullish_cross)
  - `prev_above is True` → `prev_above == 1` (death_cross, macd_bearish_cross)
  - `None` stays inert (`None == 0/1` → False) → no false fire on a new ticker's first scan.
- **`tests/test_indicators.py`** → change `{"prev_sma_50_above_200": False}`→`0`, `True`→`1`,
  `{"prev_macd_above_signal": False}`→`0` in `test_golden_cross_requires_staircase`,
  `test_death_cross`, `test_macd_bullish_cross`. Add a round-trip regression test:
  write state via `StateStore.save_ticker_state(...=1/0)`, read back, feed to
  `detect_signals`, assert the cross fires (the test that would have caught the bug).
- **Verify:** `pytest tests/test_indicators.py`.

### #10 — Advisor reads wrong key for DeepSeek
- **`watchy/advisor.py`**:
  - Add `_effective_key(llm)` → `llm.deepseek_api_key or llm.api_key` when `provider == "deepseek"`, else `llm.api_key`.
  - `get_advice()`: replace `if not llm.api_key` with `key = _effective_key(llm); if not key: warn (name the field); return None`.
  - `_call_openai_compatible` / `_call_anthropic` / `_call_gemini`: use `_effective_key(llm)` for the auth header/URL.
- **`tests/test_advisor.py`** → add `TestEffectiveKey`: deepseek + only `deepseek_api_key` → returns it;
  anthropic + `api_key` → unchanged; both empty → `""`.
- **Verify:** `pytest tests/test_advisor.py`.

### #11 — Telegram message exceeds 4096
- **`watchy/notify.py`**:
  - Add `TELEGRAM_MAX = 4096` (use ~4000 working limit).
  - Add `_split_message(text, limit)` — accumulate by `\n` lines (each line carries balanced HTML
    tags, so tag integrity is preserved). If a single line exceeds the limit (the advisor `detail`
    paragraph — plain escaped text, no tags), hard-split on whitespace.
  - `send()`: loop chunks, `_post` each, return `all(...)`.
- **`tests/test_notify.py`** (new) → 5000-char message → ≥2 chunks, each ≤ limit; no chunk splits an
  HTML tag; short message → 1 chunk; mock `_post`.
- **Verify:** `pytest tests/test_notify.py`.

**Phase-1 gate:** full `pytest` green.

---

## Phase 2 — Reliability cluster

### #9 — Concurrency (herd + locking + cross-tier mutex)
- **`watchy/daemon.py`** → `build_scheduler()`:
  - Add `jitter=300` to the Tier 1 `IntervalTrigger`; optionally stagger `start_date` by ticker index.
  - Configure executor: `BackgroundScheduler(timezone="UTC", executors={"default": ThreadPoolExecutor(max_workers=max(10, len(config.watchlist)+4))})`; per-job `misfire_grace_time` (~120s).
- **`watchy/state.py`** → `self._lock = threading.RLock()`; wrap every write
  (`save_ticker_state`, `log_signal`, `mark_notified`, `start_run`, `complete_run`) and the reads
  (`get_ticker_state`, `is_in_cooldown`) with `with self._lock:`.
- **Cross-tier per-ticker mutex** → new **`watchy/locks.py`** with a thread-safe `TickerLockRegistry`
  (`dict[str, threading.Lock]`). Instantiate once in `daemon.main`, thread through
  `_tier1_job`/`_tier2_job` → acquire in `tier1.scan_ticker` and `tier2._run_ticker` around the pipeline.
- **`tests/test_state.py`** → concurrency test (N threads, no `database is locked`).
  **`tests/test_locks.py`** (new) → same ticker → same lock; different tickers → different.
- **Risk:** signature changes ripple into job args + tier entrypoints — keep new params keyword-only,
  default `None`, so existing call sites/tests still work.

### #1 — Tier 2 inter-ticker throttle
- **`watchy/config.py`** → add `tier2_throttle_s: float = 2.0` to `WatchyConfig` + parse in `from_yaml`.
- **`watchy/tier2.py`** → `run_daily_scan`: `import time`; `if i > 0: time.sleep(config.tier2_throttle_s)`.
- **`tests/test_tier2.py`** (new) → mock `time.sleep`, assert `len(tickers)-1` calls; mock `_run_ticker`.

### #2 — yfinance disk caching (optional / dependency)
- **`requirements.txt` + `pyproject.toml`** → add `yfinance-cache` (guarded).
- **`watchy/indicators.py`** → `_fetch_history`: `try: import yfinance_cache as yf except ImportError: import yfinance as yf`. Confirm cache API matches `Ticker(...).history(...)`; ~30-min TTL.
- **`tests/test_indicators.py`** → fallback path when `yfinance_cache` absent.
- **Note:** optional — if the lib looks risky at implementation time, rely on #1 throttle and keep open.

---

## Phase 3 — Behavior fixes

### #14 — Tier 2 cadence (daily 4-analyst + Sunday 3-way risk)
- **`watchy/orchestrator.py`** → replace dead `SIGNAL_PIPELINE["scheduled_daily"]` with a helper
  `get_scheduled_spec(when: datetime) -> PipelineSpec`: `AnalystSet.FULL`, `DebateMode.BULL_BEAR`,
  `RiskMode.FULL if when.weekday() == 6 else RiskMode.SIMPLIFIED` (6 = Sunday).
- **`watchy/tier2.py`** → delete static `FULL_PIPELINE`; in `_run_ticker` call
  `get_scheduled_spec(datetime.now(timezone.utc))`. Fix the misleading module docstring.
- **Tests to update:** `tests/test_orchestrator.py::test_scheduled_daily_is_full` and
  `::test_all_signals_have_spec` reference the removed key — repoint to `get_scheduled_spec`
  (Sunday→FULL risk, weekday→SIMPLIFIED, analysts always FULL). `tests/test_e2e.py` line 74 uses
  `get_pipeline("scheduled_daily")` — repoint to `get_scheduled_spec(...)`.
- **Note:** keep a `get_pipeline` fallback so `"scheduled_daily"` as a `trigger_type` string elsewhere doesn't break.

### #8 — Level-based signals re-fire (transition-aware)
- **`watchy/state.py`** → `_init_schema`: add columns `prev_bollinger_above_upper`,
  `prev_bollinger_below_lower`, `prev_volume_anomaly`, `prev_atr_spike` (INTEGER).
  **Add a migration** `_migrate()`: `PRAGMA table_info(ticker_state)` + `ALTER TABLE ... ADD COLUMN`
  for any missing column — REQUIRED because the VPS has a live `state.db` that won't get new columns
  from `CREATE TABLE IF NOT EXISTS`.
- **`watchy/indicators.py`** → `detect_signals`: gate Bollinger/Volume/ATR on entry transition with
  truthy checks (not `is`): `now = price >= bb_upper; if now and not prev_state.get("prev_bollinger_above_upper"): fire`. Same for lower band, volume (`>=2.0`), ATR.
- **`watchy/tier1.py`** → `_update_state`: compute + persist the new flags.
- **`tests/test_indicators.py`** → entry / persist / re-entry per level-based signal.
- **Batch note:** same files as #13 (`detect_signals` + `_update_state`) — do right after #13.

### #7 — Tier 1 market-hours guard
- **`watchy/daemon.py`** → `_is_market_open()` (weekday + 13:30–20:00 UTC); guard at top of
  `_tier1_job` (log DEBUG, return). Optional `pandas_market_calendars` with weekday-only fallback.
- **`tests/test_daemon.py`** (new) → `_is_market_open` across weekday/weekend/boundary (mock `datetime`).

---

## Phase 4 — Schwab + content/enhancements

### #4 — Schwab integration (includes the former #6 bearish-skip)
- **`requirements.txt` + `pyproject.toml`** → add `schwabdev` (or `schwab-py`).
- **`watchy/config.py`** → `SchwabConfig`: add `token_path: str = "~/watchy_config/schwab_token.json"`.
- **`watchy/schwab.py`**:
  - Implement `_fetch_position` / `_fetch_all_positions` / `_fetch_account_summary` via lazy `schwabdev`.
  - **Confirmed-empty semantics (the #6 fix):** `get_position` **raises `SchwabError`** on API failure,
    returns `None` only for a genuine no-holding. Add `SchwabError`. Keep `format_position_context`
    tolerant (catch → None for display).
  - `refresh_token_age_days()` from the token file's issued-at/mtime.
- **`watchy/tier1.py`** → `_handle_signal` (after `log_signal`, before pipeline):
  `BEARISH_SKIP = {"death_cross", "macd_bearish_cross"}`; if `sig in BEARISH_SKIP`: try
  `get_position`; confirmed-`None` → lightweight "no action — not held" note + return; `SchwabError`
  → fall through and run pipeline (safe). `rsi_overbought` / `bollinger_upper_breach` deliberately
  NOT in the set (SEPA entry signals).
- **`watchy/daemon.py`** → daily token-age check job → Telegram alert when age > 6 days (7-day wall).
- **`watchy/notify.py`** → small `position_skip(ticker, signal)` helper (or reuse `send`).
- **`tests/test_schwab.py`** (new) → mock `schwabdev`: held→Position, empty→None, error→raises.
  **`tests/test_tier1.py`** (new) → bearish+empty→skip (no runner call, signal still logged);
  bearish+held→run; bearish+`SchwabError`→run; `rsi_overbought`+empty→run; Schwab disabled→run.
- **`README`** → one-time OAuth setup + weekly re-auth note.

### #3 — Telegram content (after #11)
- **`watchy/notify.py`** → `pipeline_result`: bump summary 200→400; add an analyst-verdict line;
  rely on #11 splitting for length.
- **`watchy/pipeline_runner.py`** → `_format_result`: surface a small structured verdict/count field
  if extractable from `final_state`; confirm `report_path` is always set.
- **`tests/test_notify.py`** → expanded fields present; still chunk-safe.

### #5 — Per-ticker Tier 1 price-proximity skip
- **`watchy/config.py`** → `TickerConfig`: add `target_price: float | None = None`,
  `tier1_min_price_proximity_pct: float | None = None`; add `WatchyConfig.get_ticker_config(ticker)`.
- **`watchy/tier1.py`** → `scan_ticker`: after `compute_indicators`, skip when
  `abs(price-target)/target*100 > threshold` (log INFO).
- **`tests/test_tier1.py`** → far→skip, near→scan, no fields→normal.

---

## Cross-cutting
- **Dependency manifests:** keep `requirements.txt` and `pyproject.toml` in sync (yfinance-cache,
  schwabdev, optional pandas_market_calendars).
- **DB migration:** the `_migrate()` helper from #8 is the only piece touching the live VPS `state.db`
  — test it against a pre-existing DB lacking the new columns.
- **New test files:** `test_notify.py`, `test_locks.py`, `test_tier2.py`, `test_tier1.py`,
  `test_schwab.py`, `test_daemon.py`.
- **Per-phase gate:** full `pytest`; after Phase 4, run `tests/test_e2e.py` on one ticker before deploy.
- **Signature discipline:** new params (`ticker_locks`, etc.) keyword-only with `None` defaults so
  existing call sites and tests keep working.

---

## Resolved design decisions (context)
- **#13** crossover fix → `== 0` / `== 1` (not `not prev_above`, which false-fires on first scan).
- **#14** Tier 2 → daily Market+Sentiment+News+Fundamentals (simplified risk); **Sunday** adds the
  3-way risk debate (`RiskMode.FULL`).
- **#4** Schwab → confirmed must-do; the former **#6** bearish-skip is folded in (skip only
  `death_cross`/`macd_bearish_cross` on a *confirmed-empty* position, Tier 1 only).
- **Order** → P0 (#13, #10, #11) first, then the rest; no deploy until all done.
- **Closed:** #6 (merged into #4), #12 (duplicate of #11).
