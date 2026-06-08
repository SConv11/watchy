# Watchy — Project Instructions for Claude

Watchy is a stock-monitoring daemon built on top of TradingAgents.
Tier 1 = hourly technical signal scanner (no LLM). Tier 2 = scheduled daily LLM pipeline.

## Current status — read first (updated 2026-06-08)

**Deployed & validated on the VPS (2026-06-08).** The daemon runs under systemd
(`watchy.service`, env `trading`); both pre-deploy smokes passed: `tests/test_e2e.py GOOG`
(full pipeline → manual-file position → advisor → Telegram) and `scripts/validate_yfc.py`
during Monday market hours (#2 yfc tracks the still-forming bar within 0.0112%, `Final?=False`,
`max_age=10min` — `OK — yfc compatible`). Telegram + position context confirmed working live.

The issue backlog (#1–#14) is **done**; remaining #4 items are **deferred by choice**.
Committed, pushed, 199 unit tests green; fixed issues are closed on GitHub.
**Remind the user of these at session start:**

- **#4 — position data source: backend landed (incl. real Schwab). No blocking work left.**
  - **Done:** layered `PositionSource` (`watchy/positions.py`): **Schwab API (live) → on-disk
    cached last-good snapshot (flagged stale) → manual `~/watchy_config/positions.yaml`**.
    Schwab live layer is **real, via `schwabdev`** (read-only positions + balances) — mapping/
    selection unit-tested with a faked client (`tests/test_schwab.py`). Manual-file backend
    enriches with live yfinance prices; both file & cache are age-labelled.
    **Schwab needs developer-app approval (pending) + a one-time OAuth (refresh token = 7 days);
    until then keep `schwab.enabled: false` and rely on the manual file.**
    `schwabdev` in requirements/pyproject; config keys in `secrets.example.yaml`.
  - **Deferred by user (2026-06-08):** the Tier 1 **bearish-skip** (former #6) is **dropped for
    now** — its only payoff is LLM-cost savings, not worth the missed-alert risk of inferring
    "not held" from a manual file. **Revisit only when Schwab is live & authoritative**, gated so
    the skip fires solely on an authoritative live "confirmed-empty" (file/cache/unknown → run).
  - **Optional, not built:** open orders (`account_orders`).
- **Pre-deploy smoke: DONE** (both passed on the VPS, 2026-06-08) — see the deploy note above.
- **Ops notes:** daemon env is the `trading` pyenv (`/home/watchy/.pyenv/versions/3.11.9/envs/trading/bin/python`)
  — run repo scripts with *that* python (the bare `python` shim lacks `yfinance_cache`, harmless
  fallback). `positions.yaml` is hand-maintained (update holdings + `as_of` when they change).
  Tier 1 = every 30 min/ticker (jitter ±5 min, market-hours gated); Tier 2 = daily 11:30 UTC
  (Sat skipped). Job errors are pushed to Telegram; startup/config errors only hit the journal
  (`journalctl -u watchy -f`).

This block can be trimmed next session now that the deploy is validated; keep the deferred-#4
and ops notes.

## Cross-machine workflow (local + VPS, synced via Git)

This repo is worked on from **two machines** (local + VPS) and kept in sync through Git (`origin/main`).

- **`git pull` before starting any work session.**
- **`git push` at every checkpoint and at session end.**
- **Commit at each checkpoint** — don't let a finished, tested unit of work sit uncommitted.
  Each commit message briefly describes what changed and references the issue number(s) it
  addresses (e.g. `Fix #9 concurrency …`).
- **Keep GitHub issues in sync as you go** (proactively, without being asked): when an issue is
  fixed and tests pass, close it (or comment the status if it's only partially done). The issue
  tracker should reflect reality at each checkpoint, not just at the end of the backlog.
- Commit the `.claude/` directory (shared config). Do **NOT** commit `.claude/settings.local.json`
  (machine-local; globally gitignored) or any secrets.
- **Secrets live in `~/watchy_config/secrets.yaml`, outside the repo. Never commit `.env` or secrets.**
- **If a pull/merge shows CONFLICTS: STOP and ask the human. Never auto-resolve.**
- Work directly on `main` for this repo.

## Where things live

- **Current work plan:** `docs/IMPLEMENTATION_PLAN.md` — file-by-file plan for the open issues, in execution order.
- **Bugs / decisions / enhancements:** GitHub issues (`SConv11/watchy`).
- Note: Claude's auto-memory under `~/.claude/...` is **per-machine and does NOT sync** (it's keyed by the
  project's absolute path, which differs on each machine). Cross-machine knowledge belongs here, in `docs/`,
  or in GitHub issues.

## Conventions

- Add dependencies to **both** `requirements.txt` and `pyproject.toml`.
- The live state DB on the VPS (`~/watchy/state.db`): schema changes need an `ALTER TABLE` migration,
  not just `CREATE TABLE IF NOT EXISTS`.
- Run `pytest` as the gate after each change/phase. `tests/test_e2e.py` is a manual smoke script (needs real keys).
- Per current project decision: deploy only after the whole issue backlog is done.

## Keeping docs in sync (do this proactively, without being asked)

- **`README.md`**: update it in the *same* change whenever behavior, config keys, setup, or
  operational steps change — never defer it to "later". The README must always describe the
  current state of the system.
- **`CLAUDE.md`** (this file): update it when project conventions, workflow, or architecture
  decisions change, so future sessions inherit the new ground truth.
- **`docs/IMPLEMENTATION_PLAN.md`**: the plan is allowed to change to match reality — when a
  decision is revised (e.g. a library risk reassessed), update the plan rather than silently
  diverging from it.
- Running the test/validation suites written for this repo (`pytest`, validation scripts) is
  pre-authorized — no need to ask before running them.
