# Watchy — Project Instructions for Claude

Watchy is a stock-monitoring daemon built on top of TradingAgents.
Tier 1 = hourly technical signal scanner (no LLM). Tier 2 = scheduled daily LLM pipeline.

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
