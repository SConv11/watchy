# Watchy — Project Instructions for Claude

Watchy is a stock-monitoring daemon built on top of TradingAgents.
Tier 1 = hourly technical signal scanner (no LLM). Tier 2 = scheduled daily LLM pipeline.

## How this file works

Keep CLAUDE.md lean — it loads into context every session. Durable ground truth
(conventions, workflow, architecture) lives here; dated status, ops detail, and
investigations live in `.claude/memory/*.md` (recalled on demand, committed to the repo
and synced across machines — see memory `watchy-memory-sync`). When a status block grows,
move the detail to a memory file and leave a one-line pointer here.

## Current status (2026-06-15)

Backlog #1–#18 essentially done; system deployed on the VPS and validated. Detail in memory:

- **Cost / per-component TOKENCOST** → memory `watchy-api-cost-baseline`. Sunday batch ≈ $0.54/¥3.9;
  `pro` (deep_think) model ≈30% of cost in just 2–3 calls; top nodes = Portfolio Manager + Market
  Analyst. Weekday cost (gated, no risk debate) is lower — **still to measure**.
- **Tier 2 8% proximity gate (#15/#16)** → memory `watchy-pending-enable-tier2-gate`. Enabled globally;
  self-bootstraps off `derived_target_price`. Held tickers & Sunday never gated; Tier 1 never gated.
- **Schwab live + token-expiry alerts (#4)** → memory `watchy-issue-plan`. Re-auth every ≤7 days on the
  VPS: `scripts/schwab_oauth.py --force` (must use `--force` to reset the 7-day clock).
- **VPS downsize decision** (decide before the **2026-07-02** renewal) → memory `watchy-vps-migration`.
  Leaning keep 4 GB or ~2 GB (1 GB marginal: steady-state resident ~460–500 MB + planned Docker/CouchDB
  stack). Includes the from-old-VPS capture checklist.
- **SSH airport-port workaround (sshd on 8022)** → memory `ssh-airport-port-block`.

⚠️ The auto-update timer restarts the daemon on every push — **don't push during the Tier-2 window
(~11:30–13:00 UTC)** or you interrupt the batch.

## Architecture / ops ground truth

- Daemon runs under systemd (`watchy.service`) as user `watchy`, env = `trading` pyenv
  (`/home/watchy/.pyenv/versions/3.11.9/envs/trading/bin/python`). Run repo scripts with THAT python
  (the bare `python` shim lacks `yfinance_cache`).
- Tier 1: every 30 min/ticker (jitter ±5 min, market-hours gated, event-driven). Tier 2: daily 11:30 UTC
  (Sat skipped; Sunday runs the 3-way risk debate, weekdays run 4 analysts).
- Config: `config.yaml` (committed, non-secret). Secrets: `~/watchy_config/secrets.yaml` (off-repo, never
  committed). Under systemd the daemon reads `~/watchy/config.yaml` (the repo copy — the unit does NOT set
  `WATCHY_CONFIG`), so the live watchlist can differ from origin/main; check before relying on it.
- Logs: `journalctl -u watchy -f`. Job errors → Telegram; startup/config errors → journal only.
- **TradingAgents is installed separately** (`~/TradingAgents`, `pip install -e .`) — NOT in
  `requirements.txt`/`pyproject.toml`. See the capture checklist in memory `watchy-vps-migration`.

## Cross-machine workflow (local + VPS, synced via Git origin/main)

- `git pull` before any session; `git push` at every checkpoint and at session end.
- Commit at each checkpoint — don't let a finished, tested unit sit uncommitted. Reference the issue
  number(s) in the message (e.g. `Fix #9 concurrency …`).
- Keep GitHub issues (`SConv11/watchy`) in sync as you go — close fixed ones once tests pass.
- Commit the `.claude/` directory (shared config + synced memory under `.claude/memory/`). Do NOT commit
  `.claude/settings.local.json` (machine-local, git-ignored) or any secrets.
- Work directly on `main`.
- **If a pull/merge shows CONFLICTS: STOP and ask the human. Never auto-resolve.**

## Conventions

- Add dependencies to **both** `requirements.txt` and `pyproject.toml`.
- The live VPS `state.db` (`~/watchy/state.db`): schema changes need an `ALTER TABLE` migration, not just
  `CREATE TABLE IF NOT EXISTS`.
- Run `pytest` as the gate after each change/phase (pre-authorized — no need to ask). `tests/test_e2e.py`
  is a manual smoke needing real keys.

## Where things live

- Work plan: `docs/IMPLEMENTATION_PLAN.md`. Bugs / decisions / enhancements: GitHub issues
  (`SConv11/watchy`). Cross-machine knowledge: here, `docs/`, memory (`.claude/memory/`), or issues.

## Keeping docs in sync (do proactively, without being asked)

- **`README.md`**: update in the *same* change as any behavior/config/setup/ops change — never defer it.
- **`CLAUDE.md`**: update when conventions/workflow/architecture change. Keep it lean — push detail into memory.
- **`docs/IMPLEMENTATION_PLAN.md`**: update when a decision is revised, rather than silently diverging.
