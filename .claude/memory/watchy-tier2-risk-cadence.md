---
name: watchy-tier2-risk-cadence
description: Tier 2 pipeline cadence decision — daily 4-analyst + weekly Sunday 3-way risk debate
metadata: 
  node_type: memory
  type: project
  originSessionId: b5650f24-68b0-4787-b928-29a712a1ef71
---

## Tier 2 depth/cadence decision (2026-06-05, issue #14)

Agreed design for the Tier 2 daily scan (resolves [[watchy-vps-bugs]] #14):

- **Daily (Mon–Sun):** Market + Sentiment + News + **Fundamentals** analysts,
  Bull/Bear debate, **simplified** risk.
- **Sunday only:** same 4 analysts, **RiskMode.FULL** → the 3-way
  Aggressive/Conservative/Neutral risk debate runs weekly per ticker.

**Why:** Fundamentals was missing from the old Tier 2 (the gap #14 flags). The
3-way risk debate is expensive, so run it weekly (Sunday) for guaranteed coverage
rather than daily. It also fires on `golden_cross`/`death_cross` in Tier 1, but
those are rare and depend on fixing #13 — Sunday gives belt-and-suspenders.

**How to apply:** daemon already fires Tier 2 every day (cron has no day_of_week).
Pick risk mode by weekday in `_tier2_job`/`_run_ticker`:
`RiskMode.FULL if datetime.now(timezone.utc).weekday() == 6 else RiskMode.SIMPLIFIED`
(6 = Sunday). Also fix tier2 docstring and retire/repurpose the dead
`orchestrator.SIGNAL_PIPELINE["scheduled_daily"]` entry (maybe split into
scheduled_daily = simplified, scheduled_weekly = full).

Two "debate" types, don't conflate: **Bull/Bear** (DebateMode.BULL_BEAR, runs
daily in Tier 2 + most Tier 1) vs **3-way risk** (RiskMode.FULL, now weekly Sunday).

## Holiday skip + drop Sunday, move weekly-full to first trading day (2026-07-03)

Two-step change, same day. **Final state (this is current):**

- **Tier 2 runs ONLY on XNYS trading days** — weekends AND weekday holidays (e.g.
  July 3) skipped. `_is_tier2_day()` = `is_trading_day()`.
- **The weekly full 3-way risk debate rides the FIRST trading day of the week**
  (was: Sunday). Usually Monday; **shifts to Tuesday when Monday is a holiday**, so
  the "every ticker gets one full-risk pass/week" guarantee survives holiday Mondays.
- **Dropped the standalone Sunday batch entirely.** Rationale (user-chosen, "方案A"):
  Sunday analysed the stale Friday close, then Monday's pre-open simplified run
  re-chewed the *same* Friday close — paying twice for one price basis. Consolidating
  into one Monday FULL run removes that duplication; you still get weekend news +
  full risk + a pre-week read. Est. saving ≈ one ungated full-watchlist batch/week
  (~$2/mo + ¥).
- Shared calendar helpers now in **`watchy/market_calendar.py`**: `get_calendar()`,
  `is_trading_day()`, `is_weekly_full_risk_day()` (first session of the ISO/Mon–Sun
  week via `previous_session`). daemon `_is_market_open`, orchestrator
  `get_scheduled_spec` (risk=FULL iff weekly-full-day), and tier2 `_should_skip_tier2`
  (never gate the weekly-full day) all key off these. Calendar-less fallback:
  trading day = Mon–Fri, weekly-full day = Monday.

**Supersedes** the earlier same-day "run iff Sunday OR trading session" attempt
(which kept Sunday). Tests: `test_daemon.py` (Sunday NOT a tier2 day, July-3 skip),
`test_orchestrator.py` (Mon full, midweek simplified, Memorial-Day→Tue shift),
`test_tier2_gate.py` (WEEKLY_FULL_DAY vs GATED_DAY).
