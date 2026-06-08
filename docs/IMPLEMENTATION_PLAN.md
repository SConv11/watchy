# Watchy Implementation Plan

The original file-by-file backlog (issues #1–#14) is **complete except the bearish-skip
sub-task of #4**. Finished work lives in git history and the closed GitHub issues — this
file now tracks only what's left: the #4 bearish-skip and the pre-deploy smoke steps.

## Status (as of 2026-06-08)

Done, pushed, unit-tested (192 tests green), and closed on GitHub:

- **Phase 1:** #13 crossover signals, #11 Telegram 4096 split, #10 DeepSeek advisor key
- **Phase 2:** #9 concurrency (RLock + per-ticker locks + scheduler jitter), #1 Tier 2 throttle,
  #2 yfinance-cache (with robust fallback + `max_age` staleness bound)
- **Phase 3:** #14 Tier 2 cadence (+ Saturday skip), #8 level-signal transitions (+ DB `_migrate`),
  #7 Tier 1 market-hours guard
- **Phase 4 (partial):** #5 price-proximity skip, #3 Telegram content/verdict

**Open: #4 bearish-skip only.** The #4 position-context backend has **landed** (see below);
everything else is deployable now — the position source degrades gracefully
(Schwab live → cache → manual file → no context), so nothing in the running paths requires it.

## Pre-deploy smoke steps (owner: **user**, on the VPS)

Run these before treating a deploy as live:

1. **`tests/test_e2e.py <TICKER>`** — one real end-to-end TradingAgents run (needs real keys).
2. **`scripts/validate_yfc.py` on a weekday during US market hours** — confirm #2's `max_age`
   keeps the still-forming daily bar fresh (intraday staleness couldn't be tested on a weekend).
   If yfc still serves a stale bar, add the `Final?`/`FetchDate` degrade-guard (see #2 in git log).

## #4 — Position data source  *(was: "Schwab API integration")*

**Goal — the only reason this feature exists:** know the user's current **position + open orders**
per ticker, to (a) give the advisor position context and (b) drive the Tier 1 bearish-skip.

### (a) Position-context backend — **DONE** (`watchy/positions.py`)

Settled design: a layered, robust `PositionSource` so the daemon keeps working when Schwab can't
refresh (the 7-day reauth was the blocker). Fallback chain:

```
Schwab API (live)  →  on-disk cached last-good snapshot (flagged stale)  →  manual positions.yaml
```

- **`SchwabClient`** (`schwab.py`) is the live layer — **implemented via `schwabdev`** (read-only:
  positions + balances). `get_account_summary` returns `None` on unavailable/error (schwabdev missing,
  OAuth not done, expired refresh token, API failure) and an `AccountSummary` only on genuine success.
  Lazy, cached client; account selected by `account_id` (or first linked). Mapping/selection unit-tested
  with a faked client (`tests/test_schwab.py`, 9). Needs a one-time browser OAuth on the daemon host;
  refresh token lasts 7 days. **Open orders** are not fetched yet — optional follow-up (`account_orders`).
- **`PositionCache`** writes a timestamped JSON snapshot on every successful live fetch and serves it
  (labelled with its age) when the live fetch fails — stale-but-real data survives token lapses.
- **`FilePositionSource`** reads `~/watchy_config/positions.yaml` (schema in `positions.example.yaml`)
  as the final backstop; enriches with live yfinance prices to derive market value / unrealized P&L.
  Also age-labelled: `as_of()` prefers an explicit `as_of:` field, else the file's mtime.
- **`RobustPositionSource`** memoizes one snapshot per scan and appends provenance (`source: …`) so
  stale/fallback data is never presented as live. Wired into advisor, tier1, tier2, and the e2e test.
- Tests: `tests/test_positions.py` (19) — parsing, enrichment, cache round-trip, full fallback chain.

### (b) Tier 1 bearish-skip — **OPEN** (former #6)

Not yet implemented. Needs a **tri-state** on the source: HELD / CONFIRMED-EMPTY / UNKNOWN. The
current `get_position` returns `None` for *both* not-held and no-data, which can't drive a safe skip.

- Add a tri-state query (e.g. `get_holding_status(ticker)`): CONFIRMED-EMPTY only when a backend
  authoritatively reports no holding; UNKNOWN when Schwab is stub/unavailable and there's no manual
  entry. (The manual file is authoritative for tickers it lists; absent ticker + no live = UNKNOWN.)
- Tier 1: for `death_cross` / `macd_bearish_cross` on a **confirmed-empty** position → skip the
  pipeline (lightweight "not held" note). Held / unknown / fetch-error → run the full pipeline.
  `rsi_overbought` / `bollinger_upper_breach` are **not** skipped (SEPA entry signals).

## Resolved design decisions (context)
- **#13** crossover → `== 0` / `== 1` (not `not prev`, which false-fires on a ticker's first scan).
- **#14** Tier 2 → weekdays simplified risk, **Sunday** full 3-way risk; **Saturday skipped**
  (reuses Friday's close, superseded by Sunday, nothing trades till Monday).
- **#8** level signals → fire on entry (transition-aware); `state._migrate()` ALTER TABLEs the new
  columns into the live VPS `state.db`.
- **#7** → Tier 1 only runs in the US regular session (`exchange_calendars`, DST/holiday correct);
  Tier 2 is **not** gated (weekend news/sentiment still matter).
- **Closed:** #6 (folded into #4), #12 (duplicate of #11).
