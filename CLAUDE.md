# Watchy — Project Instructions for Claude

Watchy is a stock-monitoring daemon built on top of TradingAgents.
Tier 1 = hourly technical signal scanner (no LLM). Tier 2 = scheduled daily LLM pipeline.

## Current status — read first (updated 2026-06-14)

### 2026-06-14 — PLANNED: VPS migration (do this BEFORE 2026-07-02)

**Why:** the current VPS (3-core / 4 GB) is overkill for Watchy and bills on **2026-07-02**.
Migrating to **Bandwagon (搬瓦工) LA `USCA_2`**: **20 GB disk, 1 GB RAM, 2× CPU, $50/yr**.
Must complete the move **before 2026-07-02**. Not started yet — the live capture will be
done *together with the user* in a later session (user's call: "到时候一起做"). This block
is the checklist of WHAT to capture/recreate so nothing is lost. **When we actually do it,
create `docs/VPS_MIGRATION.md` as the runbook** (user asked to defer the doc; just record
the task here for now).

- **⚠️ RAM drops 4 GB → 1 GB.** Tier 2 runs the TradingAgents LLM pipeline + pandas; 1 GB is
  tight. **Add swap (≥2 GB) on the new VPS** and watch memory during the first 11:30 UTC Tier 2
  batch (17 tickers). This is the main migration risk.

- **VPS-only state to capture from the OLD VPS (NOT reconstructable from the repo):**
  1. **TradingAgents install** — *not* in `requirements.txt`/`pyproject.toml`. Separate install
     (project_doc says `~/TradingAgents`, `pip install -e .`). Capture: source path, **git remote +
     commit**, and how it was installed. This is the #1 thing that will break a from-scratch setup.
  2. **Full `pip freeze`** of the `trading` pyenv (Python **3.11.9**) — pins the exact transitive
     LLM deps (langchain-core, deepseek, google-genai, etc.). Reproduce the env from this.
  3. **`~/watchy/state.db`** — live `derived_target_price` seeds + the `kv` table (Schwab 7-day
     clock + `KV_EXPIRY_WARNED_AT`). **Copy it over** — losing it re-bootstraps the 8% Tier 2 gate
     (a few days of higher DeepSeek cost). Schema changes need `ALTER TABLE` (see Conventions).
  4. **`~/watchy_config/`** — `secrets.yaml`, `positions.yaml`, `positions_cache.json`, and
     `schwab_tokens.db`. (Secrets stay off the repo and off the local Windows box.)
  5. **Repo working tree at `/home/watchy/watchy`** — check `git status` for **uncommitted edits**,
     esp. the **watchlist in `config.yaml`**: under systemd the daemon reads `~/watchy/config.yaml`
     (repo copy, default path — the unit does NOT set `WATCHY_CONFIG`), so the live watchlist may
     differ from origin/main. Commit/push or carry the diff over.
  6. **systemd**: `watchy.service`, `watchy-update.service`, `watchy-update.timer` (all in repo).
     Copy to `/etc/systemd/system/`, `daemon-reload`, `enable --now watchy` **and**
     `enable --now watchy-update.timer`. Confirm the timer is actually enabled on the old VPS.
  7. **Any env vars** outside `secrets.yaml` (e.g. `DEEPSEEK_API_KEY` / Gemini) — the systemd unit
     sets none, but check the old VPS shell/env in case TradingAgents reads them.
  8. **`watchy` system user** + home `/home/watchy`; pyenv + Python 3.11.9 + virtualenv `trading`.

- **New-VPS setup order:** create `watchy` user → install pyenv + Python 3.11.9 + `trading` venv →
  install TradingAgents (item 1) → `git clone` watchy to `~/watchy` + `pip install -e ~/watchy` →
  restore `~/watchy_config/` + `state.db` → copy systemd units + enable service & timer → re-run
  Schwab OAuth fresh (`scripts/schwab_oauth.py --force`, issues a new 7-day token — easier than
  migrating `schwab_tokens.db`) → `pytest` + smokes (`tests/test_e2e.py GOOG`, `scripts/validate_yfc.py`
  during market hours). Set system clock/UTC sanity (Tier 2 = 11:30 UTC).

- **SSH access to the new LA VPS (机场节点拦截 workaround — REMEMBER THIS):** the proxy/airport node
  used to reach the US-West VPS is "等级3" (US tier) with strict anti-abuse rules: **port 22 and
  passive high ports 10001–65535 are blocked**; ICMP (`ping`) works, which is why ping succeeds but
  SSH gets `Connection closed by ... port 22`. Two fixes:
  - **Plan A (recommended):** move sshd to a port in **1024–9999** (e.g. **8022**) — the airport
    unconditionally passes active ports in that range. Edit `/etc/ssh/sshd_config`, open the port in
    UFW/firewalld **and** the provider's security group, `systemctl restart sshd`, then
    `ssh -p 8022 root@<VPS_IP>`.
  - **Plan B:** point a domain (`vps.yourdomain.com`) at the VPS IP and `ssh root@vps.yourdomain.com`
    — domain-bearing requests are passed even on restricted ports (no VPS port change needed).

### 2026-06-13 — per-component DeepSeek cost tracking (TOKENCOST; commit 868c571)

Added `watchy/token_tracker.py` — a LangChain callback (`TokenCostTracker`) wired into
every Tier 2 pipeline via `TradingAgentsGraph(..., callbacks=[tracker])` in
`pipeline_runner.py`. It attributes DeepSeek token usage along two axes — **model**
(deep_think v4-pro vs quick_think v4-flash) and **graph node** (which analyst/debater/
manager made the call) — and emits **one greppable INFO line per run**:
`TOKENCOST <ticker> [<analysts>|risk<N>] usd=.. models={..} nodes={..}`. Purpose is to
see *where the daily Tier 2 cost goes* before deciding what to trim. `usd=` is a
**USD proxy** for the CNY bill (we care about per-component *share*, not absolute).
Every handler body is exception-safe — a bug here loses a measurement, never breaks a run.
**Measurement-only: no schema change, no new config, no new dependency** (langchain-core
already present). Collect after a Tier 2 batch:
`journalctl -u watchy --since today | grep TOKENCOST`.
- **Status: committed + pushed to origin/main (868c571), but NOT yet deployed on the VPS.**
  Deploy = `git pull` + `systemctl restart watchy` on the VPS (⚠️ confirm the VPS's
  uncommitted local watchlist edit before pulling). First full data = next 11:30 UTC Tier 2.
- 254 tests green. Caveat: new watchlist tickers (no `derived_target_price` seed yet)
  bypass the 8% gate for the first day or two, so early TOKENCOST totals run high before
  the gate self-bootstraps — don't misread that as a regression.

### 2026-06-10 — Schwab LIVE + token-expiry alerts (#4 done)

Schwab developer app approved and **OAuth completed on the VPS** — the live position
layer is now authoritative (verified: 8 positions fetched). Two things landed:
- **schwabdev 3.x migration.** The VPS had schwabdev **3.0.4**, a breaking API change
  vs the 2.x the code was written for. Fixes in `watchy/schwab.py`: `Client(...)` now
  takes `tokens_db=` (a **SQLite** token store, not `tokens_file=` JSON) + we pass
  `open_browser_for_auth=False` (headless VPS); `account_linked()` was renamed
  `linked_accounts()` (`account_details()` unchanged). Pin bumped to `schwabdev>=3.0.0`;
  default `tokens_path` now `~/watchy_config/schwab_tokens.db`.
- **Batch-shared position fetch + token-expiry alerting** (`watchy/schwab_health.py`).
  - **Position fetch is now fetched once per Tier 2 batch and shared across all tickers.**
    `run_daily_scan` builds ONE `RobustPositionSource` up front and passes it into every
    `_run_ticker` (signature gained a `position_source` param) — previously each ticker
    built its own and re-hit Schwab, so a 17-ticker batch = 17 redundant identical account
    calls. The per-scan source already memoizes its snapshot; sharing the instance gives
    the whole batch **one consistent holdings view + one API call**. Tier 1 unchanged in
    cadence (event-driven), but now **fetches the position BEFORE running the pipeline**
    (validates Schwab up front; holdings still feed only the advisor, not TradingAgents —
    `propagate()` has no position input. See discussion deferred: feeding holdings into TA).
  - **The 7-day refresh token used to expire silently** (live fetch fails → degrade to
    cache/manual, journal-only). Now `monitor_schwab(source)` inspects the snapshot the
    scan **already** resolved (no extra fetch): if it isn't `Schwab (live)` → **re-auth
    needed** alert; if live, a **two-stage expiry warning** — one when the refresh token
    has **≤2 days left**, a second more-urgent one at **≤1 day left** (`EXPIRY_WARN_DAYS_LEFT`).
    These use a **loud bordered format** (🔴/🟠/🚨 emoji rows + caps header) so they stand
    out from ordinary position advice. Called once per Tier 2 batch (on the shared source)
    and on each Tier 1 fired-signal scan. **No separate health-check job** — the batch fetch
    IS the daily probe. Deduped: **≤1 re-auth alert/day** + **each expiry stage once/auth
    cycle** (escalating — the `KV_EXPIRY_WARNED_AT` marker records the most-urgent tier sent;
    a later stage still fires). The 7-day clock is stamped by `scripts/schwab_oauth.py` on
    successful auth (generic `StateStore.get_kv/set_kv` + `kv` table). **254 tests green.**
- **Re-auth procedure:** every ≤7 days, on the VPS: `cd ~/watchy && ~/.pyenv/.../trading/bin/python
  scripts/schwab_oauth.py --force`. **Use `--force`** — it stashes the existing token db and
  runs the full browser OAuth, issuing a *new* 7-day refresh token and re-stamping the clock.
  A plain run (no `--force`) only refreshes the access token from the still-valid refresh token,
  which does NOT reset the 7-day window — so re-running early without `--force` is a no-op for
  expiry (this was a real point of confusion). `--force` deletes the `.bak` on success, restores
  it on failure (never loses a usable token).

### 2026-06-10 — skip-mechanism cleanup + Tier 2 gate ENABLED (commits 61eea73, 3449c1d; deployed & verified)

Resolved a "skip-mechanism incoherence" (two divergent proximity gates) and turned on
the Tier 2 cost gate:
- **Tier 1 no longer has a proximity gate** — the per-ticker `#5` skip and its
  `tier1_min_price_proximity_pct` field were **deleted**. Tier 1 is now an
  *unconditional safety net*: during market hours it always scans (market-hours +
  cooldown only), so far-from-target names still get crash/signal coverage. (This also
  removed `#5`'s latent bugs: no held-exemption + frozen `prev_*` transition state.)
- **One proximity gate remains — Tier 2 `#15`, renamed `tier2_min_price_proximity_pct`
  → `min_price_proximity_pct`.** Now has a **global default**
  (`WatchyConfig.min_price_proximity_pct`, applied to every watch-only ticker) + optional
  **per-ticker override** (same key, long-form watchlist). Held tickers and Sunday are
  never gated; Tier 1 is unaffected. Resolution: `tier2._effective_proximity_pct(tc, global)`.
- **Gate ENABLED at 8% globally** (`config.yaml` top-level `min_price_proximity_pct: 8.0`).
  Self-bootstrapping: gates against the #16 `derived_target_price`, which seeds on Tier 2
  runs — so **savings ramp over a few days** (no manual `target_price` set on any ticker;
  no-target → runs). Symmetric band → a watch-only name crashing far *below* entry is
  silenced on weekdays (covered by Tier 1 signals + Sunday).
- **`volume_anomaly_moderate` (1.5×) signal removed** as low-signal noise (was 3/8 of one
  day's Tier 1 triggers); volume now fires only `volume_anomaly_strong` (≥2×). Removed
  `volume_ratio_moderate`.
- Deployed 2026-06-10 (auto-update pull + `systemctl restart watchy`, 18 jobs, clean);
  config load verified `gate=8.0, tickers=17`. **243** unit tests green.
- **Observe/deferred:** confirm `derived_target_price` seeds after the first new-code
  11:30 UTC Tier 2; watch DeepSeek daily cost vs ¥4/day baseline. Deferred by choice:
  coalescing same-scan multi-signal Tier 1 runs (latent, low priority).

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
