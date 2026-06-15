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
