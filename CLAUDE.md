# Watchy — Project Instructions for Claude

Watchy is a stock-monitoring daemon built on top of TradingAgents.
Tier 1 = hourly technical signal scanner (no LLM). Tier 2 = scheduled daily LLM pipeline.

## Current status — read first (updated 2026-06-14)

### 2026-06-14 — VPS downsize decision: DEFERRED, pending live Tier-2 RAM-peak data

**Status:** migration not active work *yet*, but it's an **open decision the user is actively
tracking**: whether to downsize from the current VPS (3-core / 4 GB, overkill, **bills 2026-07-02**)
to **Bandwagon (搬瓦工) LA `USCA_2`** (20 GB / 1 GB / 2× CPU / $50/yr). **The deciding input is the
live Tier-2 RAM peak** (open thread below). **Decide before the 2026-07-02 renewal:** if the peak
leaves comfortable headroom on 1 GB → switch (saves money); if it runs hot → renew the current VPS.
Capture checklist + SSH workaround further down are reference for *if* we switch.

- **🆕 2026-06-14 — the VPS is becoming MULTI-TENANT (changes the downsize math).** User plans to run
  **Docker Engine + docker compose + a CouchDB container (Obsidian LiveSync) + Cloudflare Tunnel
  (cloudflared)**, and *maybe* a web backend (domain use undecided — only if GitHub Pages isn't
  enough). Known new baseline = Docker (~70–100 MB) + CouchDB (~100–150 MB, spikes on compaction) +
  cloudflared (~30–50 MB) ≈ **+200–300 MB before any web backend.** Stacked on Watchy's Tier-2 peak
  (459 MB Sun; weekday unmeasured), this likely pushes a **1 GB box into swap during the daily batch
  window** — and swap hurts the *interactive* tenants (LiveSync sync, web), not the batch daemon.
  **Provisional verdict: 1 GB downsize now marginal-to-not-recommended → keep the 4 GB, or pick a
  ~2 GB tier.** Notes: Cloudflare Tunnel = outbound-only ingress (no inbound ports; it can also carry
  SSH and **obsolete the 8022 airport-port hack** — see SSH section below). Keep CouchDB off the public
  net (localhost-bound, exposed only via the tunnel + Cloudflare Access). Watchy runs on the host
  (systemd) while the new stack is containerized → don't bind-mount `~/watchy_config` into any
  container. Disk: 20 GB gets tight with Docker images — watch it.

- **⏳ OPEN THREAD — Tier-2 RAM peak (drives the downsize decision):**
  - **Measured so far:** live `watchy.service` **idle baseline = 150 MB** (`MemoryPeak`, CPU 3.17 s),
    over an 18h uptime (since 2026-06-13 09:31 UTC). ⚠️ **That window had NO Tier 2 run** — Sat
    06-13 is skipped and it was the weekend (Tier 1 market-hours-gated off), so **no `propagate()`
    LLM pipeline ran**. 150 MB is the *idle* baseline only, **not** a Tier-2 peak.
  - **Cross-check (local proxy, Windows/py3.13):** full import stack (numpy+pandas+yfinance+
    yfinance_cache+langchain_core+`TradingAgentsGraph`) ≈ **205 MB RSS**; **imports dominate, market
    data negligible** (~2.5 MB for 17 tickers). Linux/py3.11 lower — consistent with the live 150 MB.
  - **✅ Measured 2026-06-14 (Sun, 3-way risk-debate Tier 2):** `MemoryPeak = 483,819,520 B ≈ 461 MiB`
    (climbed 459→461 after the batch finished). Single-pipeline peak, weekend (Tier 1 market-hours-gated
    off) → **no concurrency**, NOT the absolute max. ⚠️ **MEASUREMENT WAS ON STALE CODE** — see the
    auto-update bug below; the running daemon was 06-13 vintage (pre-TOKENCOST, old watchlist). RAM still
    representative (TOKENCOST is zero-cost), but the live watchlist size may push the real peak a bit higher.
  - **🔑 KEY FINDING — the daemon does NOT return to the 150 MB idle baseline after a batch.** At 13:37
    UTC, ~2h *after* the 11:30 batch, `MemoryCurrent` was still **461 MiB** (≈ peak). CPython doesn't
    return freed arenas to the OS, so the **resident floor in steady daily operation is ~460+ MB, not
    150.** The 150 MB "idle" was an artifact of measuring *before the first batch / right after a restart*.
    **This invalidates the earlier "459 < 500 → 1 GB comfortably viable" reasoning:** in steady state
    Watchy holds ~460–500 MB continuously between restarts, and on a multi-tenant box (Docker+CouchDB+
    cloudflared ≈ +250 MB) that's ~710–750 MB resident *before* any peak or web backend → **1 GB not
    viable; keep 4 GB or use ~2 GB.** (Watch over several days: if `MemoryPeak` climbs each day with no
    restart it's a leak, not just arena retention — frequent auto-restarts now mask it.)
  - **Still to measure (the real ceiling):** a **weekday 11:30 UTC** run — different shape (4 analysts)
    AND, because a 17-ticker sequential batch can run past 13:30 UTC (US open, EDT), **Tier-1 fired
    pipelines can stack on the still-running Tier-2 batch** (pool ≈20). That concurrency is what today's
    weekend number does NOT capture, so 459 MB is a strong favorable data point but **not yet the
    provable max**. Read after a weekday batch:
    `systemctl show watchy -p MemoryPeak -p MemoryCurrent` (don't restart the service or the high-water
    mark resets). sysstat (10-min default) gives a system-wide RAM/swap series; `sar -r 30 180` for finer shape.
  - **Decision rule:** Watchy idle 150 MB; **Tier 2 sequential** (`tier2.py:57`) → one pipeline at a
    time. On 1 GB (≈900 MB usable) minus minimal Ubuntu (~100–150 MB): a Tier-2 peak **under ~500 MB
    → 1 GB comfortably viable**; approaching ~700 MB or driving sustained swap → stay on a bigger box.
    Add **1–2 GB swap** on a 1 GB host regardless (insurance for Tier-1 bursts; pool
    `max(10, len(watchlist)+4)≈20`, `daemon.py:69`). Record the actual numbers here as they come in.

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
     **⚠️ REQUIRED: the sudoers drop-in `/etc/sudoers.d/watchy-autoupdate`** containing
     `watchy ALL=(root) NOPASSWD: /usr/bin/systemctl restart watchy` (mode 0440). `auto-update.sh` runs
     as `User=watchy` and restarts via `sudo systemctl restart watchy`; **without this drop-in the pull
     succeeds but the restart silently fails and the daemon runs STALE code indefinitely** — exactly the
     bug found 2026-06-14 (disk at `9ffe27d`, daemon still on the 06-13 boot, ~1 day stale).
     **FIXED + DEPLOYED 2026-06-14** (commit `a5331a3`: sudo restart + `--ff-only` + loud errors;
     sudoers drop-in created; daemon restarted onto current code at 13:53 UTC — TOKENCOST + live
     watchlist now active). A standing `chmod +x` mode-diff on the VPS's `auto-update.sh` also had to
     be discarded (`git checkout --`) so the script update could pull. Recreate the sudoers drop-in on
     any new VPS. Verify with `sudo visudo -c`.
  7. **Any env vars** outside `secrets.yaml` (e.g. `DEEPSEEK_API_KEY` / Gemini) — the systemd unit
     sets none, but check the old VPS shell/env in case TradingAgents reads them.
  8. **`watchy` system user** + home `/home/watchy`; pyenv + Python 3.11.9 + virtualenv `trading`.

- **New-VPS setup order:** create `watchy` user → install pyenv + Python 3.11.9 + `trading` venv →
  install TradingAgents (item 1) → `git clone` watchy to `~/watchy` + `pip install -e ~/watchy` →
  restore `~/watchy_config/` + `state.db` → copy systemd units + enable service & timer → re-run
  Schwab OAuth fresh (`scripts/schwab_oauth.py --force`, issues a new 7-day token — easier than
  migrating `schwab_tokens.db`) → `pytest` + smokes (`tests/test_e2e.py GOOG`, `scripts/validate_yfc.py`
  during market hours). Set system clock/UTC sanity (Tier 2 = 11:30 UTC).

- **SSH through the airport proxy (机场节点拦截 workaround — BATTLE-TESTED on hil-2 2026-06-14):**
  the proxy/airport node ("等级3" US tier) **blocks port 22 and passive high ports 10001–65535**, but
  **unconditionally passes active ports 1024–9999**; ICMP passes too (so `ping` works but `ssh`:22
  gets `Connection closed`). Fix = run sshd on a port in 1024–9999 (we use **8022**). **DONE on the
  current hil-2 box; redo on any new VPS.**
  - **⚠️ Ubuntu 22.10+/24.04 socket-activates sshd (`ssh.socket`).** Editing `Port` in `sshd_config`
    does nothing (the socket owns the port), AND the socket route is **unreliable for a 2nd port** —
    `systemctl edit ssh.socket` with bare `ListenStream=22/8022` left the extra port "closed" (single
    `sshd -D` doesn't service the extra fd) and dropped the **IPv4** listeners → **IPv4 refused on
    BOTH ports, near-lockout** (recovered via the Hetzner web console). Don't use the socket route.
  - **✅ Working method = ditch socket activation, use classic sshd** (keep 22 as a fallback +
    out-of-band console open while doing this):
    ```bash
    printf 'Port 22\nPort 8022\n' | sudo tee /etc/ssh/sshd_config.d/port.conf
    sudo sshd -t                              # validate config
    sudo systemctl disable --now ssh.socket
    sudo systemctl enable --now ssh.service
    sudo systemctl restart ssh.service        # MUST restart explicitly; enable --now won't restart a running unit
    sudo sshd -T | grep -i '^port'            # expect: port 22  +  port 8022
    ss -tlnp | grep -E ':22|:8022'            # expect 0.0.0.0 + [::] on both, owned by sshd
    sudo ufw allow 8022/tcp                    # if ufw active
    ```
  - **Verify in order** (each removes one variable): loopback on VPS `ssh -p 8022 -l watchy 127.0.0.1`
    (host-key prompt = sshd serves 8022) → laptop **proxy OFF** `ssh -p 8022 -l watchy <IP>` (IPv4/ufw)
    → laptop **proxy ON** (the goal: airport passes 8022). Use **`-l watchy`** not `watchy@host` — a
    stray space before `@` makes ssh treat the *username* as the host (proxy fake-IP `198.18.0.0/15` in
    the error = you hit the proxy's made-up IP, not the server).
  - **Keep port 22** as a direct-access fallback (blocked via the airport anyway → no real exposure).
    **Recovery if locked out:** out-of-band console — **Hetzner Cloud Console** for hil-2,
    **Bandwagon KiwiVM** for the LA box. Bandwagon has **no cloud security group** (OS firewall only).
  - **Plan B (no VPS change):** point a domain at the IP and `ssh user@vps.yourdomain.com` — the
    airport passes domain-bearing requests even on restricted ports.

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
