# Watchy Implementation Plan

The original file-by-file backlog (issues #1–#14) is **complete except #4**. Finished
work lives in git history and the closed GitHub issues — this file now tracks only what's
left: the #4 position-data-source decision and the pre-deploy smoke steps.

## Status (as of 2026-06-07)

Done, pushed, unit-tested (160 tests green), and closed on GitHub:

- **Phase 1:** #13 crossover signals, #11 Telegram 4096 split, #10 DeepSeek advisor key
- **Phase 2:** #9 concurrency (RLock + per-ticker locks + scheduler jitter), #1 Tier 2 throttle,
  #2 yfinance-cache (with robust fallback + `max_age` staleness bound)
- **Phase 3:** #14 Tier 2 cadence (+ Saturday skip), #8 level-signal transitions (+ DB `_migrate`),
  #7 Tier 1 market-hours guard
- **Phase 4 (partial):** #5 price-proximity skip, #3 Telegram content/verdict

**Open: #4 only.** Everything else is deployable now — Schwab is a safe stub
(`enabled=False` → returns `None`), so nothing in the running paths requires it.

## Pre-deploy smoke steps (owner: **user**, on the VPS)

Run these before treating a deploy as live:

1. **`tests/test_e2e.py <TICKER>`** — one real end-to-end TradingAgents run (needs real keys).
2. **`scripts/validate_yfc.py` on a weekday during US market hours** — confirm #2's `max_age`
   keeps the still-forming daily bar fresh (intraday staleness couldn't be tested on a weekend).
   If yfc still serves a stale bar, add the `Final?`/`FetchDate` degrade-guard (see #2 in git log).

## #4 — Position data source  *(was: "Schwab API integration")*

**Goal — the only reason this feature exists:** know the user's current **position + open orders**
per ticker, to (a) give the advisor position context and (b) drive the Tier 1 bearish-skip.

**Design is OPEN — to discuss next session.** Schwab API is blocked for now (OAuth setup + the
7-day refresh-token reauth burden). Reframe the feature around an **abstract position source** with
raise-on-uncertainty semantics; Schwab becomes one backend among several:

| Backend | Pros | Cons |
|---------|------|------|
| **Manual file** (`~/watchy_config/positions.yaml`) | trivial, no OAuth, clean held/empty for bearish-skip | manual upkeep |
| **Email monitoring** (parse Schwab trade-confirmation emails) | no OAuth / no reauth / no API creds | fragile: reconstruct state from fills, needs an initial snapshot, eventual-consistency, open-order coverage gaps |
| **Schwab API** (`schwabdev` / `schwab-py`) | real-time, authoritative | OAuth setup + 7-day manual reauth |

**Recommended near-term:** abstract the position interface, implement the **manual-file backend
first** (unblocks the advisor + bearish-skip without OAuth); revisit email vs Schwab later.

**Bearish-skip semantics (carry over from the former #6, regardless of backend):**
- `get_position` **raises** on fetch failure; returns `None` only for a genuine no-holding.
- Tier 1: for `death_cross` / `macd_bearish_cross` on a **confirmed-empty** position → skip the
  pipeline (lightweight "not held" note). Held / fetch-error / not-configured → run the full
  pipeline. `rsi_overbought` / `bollinger_upper_breach` are **not** skipped (SEPA entry signals).

## Parked for next discussion
- **Email-monitoring** (and manual-file vs Schwab) as the position-tracking backend — captured
  above under #4. Decide the backend before implementing.

## Resolved design decisions (context)
- **#13** crossover → `== 0` / `== 1` (not `not prev`, which false-fires on a ticker's first scan).
- **#14** Tier 2 → weekdays simplified risk, **Sunday** full 3-way risk; **Saturday skipped**
  (reuses Friday's close, superseded by Sunday, nothing trades till Monday).
- **#8** level signals → fire on entry (transition-aware); `state._migrate()` ALTER TABLEs the new
  columns into the live VPS `state.db`.
- **#7** → Tier 1 only runs in the US regular session (`exchange_calendars`, DST/holiday correct);
  Tier 2 is **not** gated (weekend news/sentiment still matter).
- **Closed:** #6 (folded into #4), #12 (duplicate of #11).
