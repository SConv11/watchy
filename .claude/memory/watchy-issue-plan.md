---
name: watchy-issue-plan
description: Backlog status — #1–#16 done (incl. #3 truncation refix, #15 Tier 2 gate, #16 auto-target); #17 (close-the-loop) + #18 (LLM comparative analysis) open by choice; #4 Schwab LIVE (app approved + OAuth done 2026-06-10)
metadata:
  node_type: memory
  type: project
  originSessionId: b5650f24-68b0-4787-b928-29a712a1ef71
---

## Session 2026-06-10 — 跳过机制梳理:删 #5 + 删 volume_moderate（commit 61eea73, pushed）

排查"跳过机制混乱"后,定下 **Tier 1 = 无条件安全网**(不做邻近门控),并削掉一个噪声信号。已做、已测(235 green)、已推 origin/main:
- **删 Tier 1 邻近门控(#5)**:它和 Tier 2 门控(#15)语义分叉(无 held 豁免、无周日规则、只读手动 target、跳过时冻结 `prev_*` 转换 state)。删后 Tier 1 只剩 市场时段 + 冷却 + 信号检测。移除 `tier1_min_price_proximity_pct` 字段 + `_is_outside_proximity`。`target_price` 字段**保留**(Tier 2 还用)。
- **删 `volume_anomaly_moderate` 信号(1.5×)**:实测某交易日 8 次 Tier 1 触发里占 3 次,是最弱信号却仍花一次 LLM。改为只触发 `volume_anomaly_strong`(≥2×),`compute_level_states` 阈值 1.5→2.0。移除 `volume_ratio_moderate`。
- 文件:`tier1.py / indicators.py / config.py / orchestrator.py / notify.py` + 测试 + 文档(README/README.en/project_doc/config.yaml)。
- ⚠️ **重新部署前提醒用户**:实时 `~/watchy/config.yaml` 若设了 `tier1_min_price_proximity_pct` 或 `volume_ratio_moderate`,daemon 重启会因 `**kwargs` 构造报错。两者本就 inert/默认,基本不会设,但 pull+restart 前最好核一眼。
- **未做(用户说"先做这两个,其余再议")**:① `tier2_min_price_proximity_pct`→ 改名 `min_price_proximity_pct`(现 inert,零成本);② 合并同票多信号(潜在保险,昨天没触发);③ 启用 Tier 2 门控(给 watch-only 票加 8%,省 DeepSeek)。详见 [[watchy-api-cost-baseline]] / [[watchy-pending-enable-tier2-gate]]。

## Session 2026-06-09 — message redesign + #15/#16

- **#3 truncation REFIX (commit 519b60a).** Earlier close only bumped 200→400; the
  per-field cuts (analyst dumps@300, risk@500, summary@400) still chopped mid-word.
  Now Telegram "Analysis Complete" msg keeps only two **digested** blocks in FULL
  (chunked if long): **Trader Plan** (new `trader_plan` field = `trader_investment_plan`)
  + **Risk / Final Call** (`risk_assessment`, no 500 cap). Raw per-analyst report dumps
  dropped from msg body — they're in the attached `.md`. Key insight: TA's
  `judge_decision == final_trade_decision` (portfolio_manager.py 75&89), so verdict/risk/
  summary all traced to one string → collapsed. Sparse market-only → falls back to summary.
- **#15 Tier 2 proximity gate + #16 auto-target (commit 320ace7).** Opt-in per ticker
  `tier2_min_price_proximity_pct`: weekdays skip Tier 2 if price > N% from effective target;
  **Sunday always runs**; **Tier 1 never gated**. Shared `watchy/proximity.py`
  `is_outside_proximity(price, target, pct)` now used by both tiers (tier1 keeps tc-wrapper).
  #16: advisor emits structured `Target:` line → `parse_price` ($/commas/range→midpoint, N/A→None)
  → persisted to `ticker_state.derived_target_price` (ALTER TABLE migration). Effective target =
  manual `config.target_price` else derived (manual wins). 229 tests green.
- **Held-ticker fix (commit b6987cf, user-flagged).** Original gate used ONE ambiguous
  `Target:` (entry OR exit) + symmetric proximity, ignoring held status → could skip a HELD
  position as it drifts toward its stop. **Decision (Option A): a held ticker is NEVER gated**
  — `_run_ticker` resolves position source before the gate, passes `held` into `_should_skip_tier2`;
  `_is_held` treats lookup error as held (conservative). Gate is now watch-only. `Target:` reframed
  to mean **entry/accumulation level ONLY** (explicitly not stop/take-profit) → consistent semantics.
- **DEPLOYED & SMOKED on VPS (2026-06-09 ~14:46 UTC).** `git pull` + `systemctl restart watchy`
  done; daemon active, scheduler started with 18 jobs, no traceback; state.db migration ran clean
  (derived_target_price/ts). `validate_target_extraction.py` passed against **live Gemini
  (gemini-3.5-flash)**: emitted `Target: 230.00 - 246.00` → parsed 238.00, decision=ADD — and
  correctly picked the ENTRY zone, not the stop/take-profit (entry-only reframing confirmed live).
  Caveat resolved. NOTE: pytest is NOT installed in the trading env (dev-only) — that's expected;
  run unit tests locally. The #15 gate is still inert (no ticker sets `tier2_min_price_proximity_pct`).
- **#19 (commit cb9e6dd + 6fdfbdb): cash in concentration math.** Manual-file source used a
  stock-only total → false over-concentration TRIM. Fix: positions.yaml accepts
  **`total_account_value`** (preferred, authoritative denominator) or `cash` (added to live stock
  value); total wins if both, a total below equities is ignored. Advisor prompt mandates
  Total-Account-Value denominator. Schwab path was already correct (liquidationValue). User must
  add `total_account_value:` to their positions.yaml for it to take effect.
- **#18 created** (LLM comparative analysis: model × prompt-fidelity grid for advisor; details TBD).
  **#17** (close-the-loop umbrella) still open by choice. Both depend on faithful structured
  extraction from analysis — today's untruncated `trader_plan`/`risk_assessment` are the raw material.

## Backlog status (updated 2026-06-08)

Issues #1–#14 are **DONE except the bearish-skip sub-task of #4**. All committed +
pushed to origin/main, **192** unit tests green, fixed issues closed on GitHub.
Authoritative cross-machine record: repo `CLAUDE.md` ("Current status" block) +
`docs/IMPLEMENTATION_PLAN.md`. This memory is per-machine; trust the repo docs first.

Done: #13 #11 #10 (P0) · #9 #1 #2 (reliability) · #14 #8 #7 (behavior) · #5 #3.
Notable: #2 yfinance-cache added with robust fallback + `max_age` staleness bound;
#14 also **skips Saturday** Tier 2 (redundant with Sunday). See [[watchy-tier2-risk-cadence]].

## #4 — position data source: backend LANDED, bearish-skip OPEN

**Decision (this session):** user will use the **Schwab API**, but wants it robust so
the daemon works when Schwab can't refresh. Landed a layered `PositionSource`
(`watchy/positions.py`, commit b0219de): **Schwab live → on-disk cached last-good
snapshot (flagged stale) → manual `~/watchy_config/positions.yaml`**.
- `SchwabClient` live layer = **real, via `schwabdev`** (read-only positions+balances);
  `get_account_summary` returns None on unavailable/error (pkg missing, OAuth undone, expired
  7-day refresh token, API fail), AccountSummary only on real success → composite falls back.
  Lazy cached client, account picked by `account_id` (or first linked). Faked-client tests in
  `tests/test_schwab.py`. **User registers Schwab app + does one-time browser OAuth on the host.**
  `schwabdev>=2.4.0` in requirements+pyproject; config keys (callback_url, tokens_path) in
  secrets.example.yaml. **Open orders NOT fetched yet** — optional follow-up via `account_orders`.
- `PositionCache` (JSON in `~/watchy_config/positions_cache.json`) snapshots good fetches,
  serves them with age label on failure. `FilePositionSource` enriches via yfinance price.
- `RobustPositionSource` memoizes one snapshot/scan, appends `source: …` provenance.
- Schema example: `positions.example.yaml`. 19 new tests in `tests/test_positions.py`.

**Tier 1 bearish-skip (former #6) — DROPPED for now (user decision 2026-06-08).** Its only
payoff is LLM-cost savings on a bearish cross for a non-held name — not worth the failure mode.
Can't safely判定 "confirmed-empty" from the manual file: user won't write tickers as quantity:0,
and an opt-in "file authoritative" flag would go stale/forgotten (forgotten holding → its death
cross wrongly skipped = missed sell alert). **Revisit ONLY when Schwab is live & authoritative**,
gated so skip fires solely on authoritative live confirmed-empty; file/cache/unknown/error → run.
rsi_overbought/bollinger_upper_breach never skipped (SEPA entries). Email-monitoring backend idea
also dropped (Schwab chosen). **Open orders** = optional, not built (`account_orders`).

**Schwab status (UPDATED 2026-06-10): LIVE.** Developer-app approved, one-time OAuth done on the
VPS (8 positions fetched, verified). `schwab.enabled: true`; live layer is now authoritative.
Details in repo `CLAUDE.md` — summary:
- **schwabdev 3.x migration** (VPS had 3.0.4, breaking vs 2.x): `Client(...)` takes `tokens_db=`
  (SQLite, not `tokens_file=` JSON) + `open_browser_for_auth=False` (headless); `account_linked()`
  → `linked_accounts()`. Pin `schwabdev>=3.0.0`; `tokens_path` default now `…/schwab_tokens.db`.
- **Position fetch shared per Tier 2 batch** (one source → all tickers, was 17 redundant calls);
  Tier 1 fetches before the pipeline. Fallback unchanged (live → cache → manual file).
- **Token-expiry alerts** (`watchy/schwab_health.py` `monitor_schwab`): the 7-day refresh token
  expiring is no longer silent — Telegram alert on "re-auth needed" plus a **two-stage expiry
  warning (≤2 days left, then ≤1 day left)** with a **loud bordered format** (🔴/🟠/🚨 + caps)
  so it stands out from position advice. Each stage once per auth cycle, escalating.
- **OPS: re-auth every ≤7 days** on the VPS with the trading-pyenv python:
  **`scripts/schwab_oauth.py --force`** — MUST use `--force` to get a new 7-day token (it stashes
  the token db → full browser OAuth → restamps clock; restores `.bak` on failure). A plain run
  only refreshes the *access* token and does NOT reset the 7-day window (this confused the user
  once). Clock kv = `schwab_auth_at`.

## Deploy — DONE & validated on VPS (2026-06-08)

Both pre-deploy smokes passed:
1. `tests/test_e2e.py GOOG` — full pipeline → manual-file position ($1,966 portfolio, GOOG
   +20.9%) → advisor → Telegram. Caught & fixed a Telegram 400 (sendMessage payload missing
   chat_id) live.
2. `scripts/validate_yfc.py` (Mon market hours) — yfc tracks the still-forming bar within
   0.0112%, `Final?=False`, `max_age=10min`, `OK — yfc compatible`.

Daemon live under systemd `watchy.service` (env `trading`). **Run repo scripts with the trading
env python** (`/home/watchy/.pyenv/versions/3.11.9/envs/trading/bin/python`) — the bare `python`
shim lacks `yfinance_cache` (harmless fallback, but won't exercise the cache). Tier 1 = 30min/
ticker (jitter ±5min, market-gated); Tier 2 = daily 11:30 UTC (Sat skipped). Job errors → Telegram;
startup errors → journal only.

## Git/issue workflow note
`gh` CLI on the local Windows machine fails on `api.github.com` through the Clash
proxy (EOF); `curl` works. Use `gh auth token` + curl REST to read/close issues.
See [[watchy-git-workflow]].
