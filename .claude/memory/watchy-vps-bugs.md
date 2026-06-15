---
name: watchy-vps-bugs
description: VPS 上 watchy 待修/已修 bug 状态追踪
metadata:
  type: project
  node_type: memory
  originSessionId: c4282d72-1ba4-455f-8406-7514d76f13a1
---

## VPS Bug 状态 (2026-06-03)

### ✅ 已解决
1. **Telegram HTTP 400** — HTML escape (commit `2a6ece5`)
2. **VPS 旧 config** — 默认路径改为 `~/watchy/config.yaml`（git 管理），secrets 仍独立
3. **SQLite 线程错误** — `check_same_thread=False`
4. **watchy yfinance session** — 删 `requests.Session`，兼容 1.x
5. **TradingAgents yfinance session** — 同上，+ fallback catch YFRateLimitError

### ⚠️ 待观察
6. **Tier 2 yfinance 批量 429** — 16 只票同时跑可能瞬间 100+ API 请求
   - 当前状态：未加保护，等 Tier 2 (11:30 UTC) 跑完看日志
   - 方案 A: `tier2.py` 循环加 `time.sleep(2)`
   - 方案 B: [yfinance-cache](https://github.com/ValueRaider/yfinance-cache) — 本地缓存层，减少 API 调用

### ✅ 已确认不影响
- VPS yfinance 429 — Hetzner IP 阈值高，暂未触发

## 第二轮扫描新增 bug (2026-06-05，已提 issue)

GitHub issue #1–#12 已涵盖部分。新发现并提交：

- **#13 (Critical)** — 交叉信号在生产环境永不触发。`indicators.detect_signals`
  用 `prev_above is False`/`is True` 比较，但 `StateStore` 存的是 SQLite int（0/1），
  `0 is False`/`1 is True` 在 CPython 都是 False。导致 golden_cross / death_cross /
  macd_bullish_cross / macd_bearish_cross 四个信号全废。测试传 Python bool 掩盖了 bug。
  修复：改 `== 0`/`== 1` 或 truthiness，并把测试改成传 int。
- **#14 (Medium)** — Tier 2 daily scan 实际跑 MARKET_SENTIMENT_NEWS + SIMPLIFIED，
  但 docstring 称 "full 4-analyst + full risk"；orchestrator 的 `scheduled_daily`
  spec (FULL/FULL) 是死代码，tier2 从不读它。两处定义不一致。

### 未提 issue 的低置信观察
- `_fetch_history` 的 fallback `yf.download(ticker, ...)` 在 yfinance 1.x 单票时
  可能返回 MultiIndex 列 → `"Close" not in df.columns`。需联网验证再决定是否提。
- `state.mark_notified` 是死代码，`signal_log.notified` 永远为 0（无人读，无害）。
