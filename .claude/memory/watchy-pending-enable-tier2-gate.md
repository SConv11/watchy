---
name: watchy-pending-enable-tier2-gate
description: Tier 2 邻近门控已启用（全局 8%）+ 改名 min_price_proximity_pct；待 VPS pull+restart 生效
metadata:
  node_type: memory
  type: project
  originSessionId: ddb31c61-4117-40bf-8ff9-59260ba6c64f
---

**状态变更（2026-06-10）：#15 Tier 2 邻近门控已从 inert → 启用。** 之前的"提醒用户启用"已完成。

本次改动（commit 3449c1d, pushed origin/main）：
- **改名**：per-ticker `tier2_min_price_proximity_pct` → `min_price_proximity_pct`（删 #5 后只剩这一个邻近门控，见 [[watchy-issue-plan]]）。
- **加全局默认**：`WatchyConfig.min_price_proximity_pct`，套到所有 watch-only 票，按票可用同名键覆盖；解析器 `tier2._effective_proximity_pct(tc, global_pct)`（per-ticker 优先，否则全局）。
- **启用**：`config.yaml` 顶层 `min_price_proximity_pct: 8.0`。watchlist 是短表 17 只，所以用全局默认而非逐票（逐票太丑）。持仓票 + 周日 永不门控；Tier 1 不受影响。

**⚠️ 待用户在 VPS 操作才生效**：`git pull` + `systemctl restart watchy`。config.yaml 就是仓库这份（用户确认无本地特殊版），所以 pull 即更新，无字段冲突风险。

**自举行为（要知道）**：门控靠 effective target（无手动 `target_price`，全靠 #16 `derived_target_price`）。没 target 的票门控**安全降级=照跑**。derived target 由 Tier 2 在新代码上跑时种下（首个新代码 Tier 2 ≈ 2026-06-10 11:30 UTC 起）。所以启用后**先种 target、几天后才真正开始 skip**，省钱效果渐显。

**启用后观察**：DeepSeek 日成本应下降（见 [[watchy-api-cost-baseline]] 基线 ¥4/天）；同时留意有没有该分析的 watch-only 票被误跳（远低于入场价的暴跌会被对称门控静音——靠 Tier 1 信号 + 周日兜底，见 [[watchy-issue-plan]] 的盲点讨论）。

---

**ATR 自适应门控 + Tier 2 优先级排序（2026-06-16，已实现 commit c5316f9，本地已测 276 passed，待 push 部署）。** 把固定 8% 升级成按票自适应：`band_pct = mult × ATR%`（`ATR% = avg_atr_20d / price × 100`，即"价格离目标超过 mult 个交易日的常规波动 → 跳过"）。决策：
- **opt-in 共存**：新增 `atr_proximity_mult`（全局 + 按票）。不设 → 完全是今天的固定 pct 行为（部署零行为变化）。设了且 ATR 可用 → 用 ATR；否则降级回固定 pct。
- **mult 先跑校准脚本再定**（不预拍数）。
- 数据现成：`compute_indicators` 已算 `bundle.avg_atr_20d`/`atr`，`tier2._run_ticker` 在门控前（`tier2.py:88`）就拿到了 bundle → **不需要 state 迁移、不需要额外抓数**。
- **必须 clamp** ATR 推导值到 `[floor, ceiling]`（拟默认 4%–20%，代码里给默认）。
- proximity.py 保持纯函数不动；ATR 逻辑放进 `tier2._effective_proximity_pct`（改签名吃 bundle 的 avg_atr + price）。

**已落地（commit c5316f9）**：
- **机制全做完且 opt-in**：`atr_proximity_mult`（全局+按票）+ `proximity_pct_floor/ceiling`(默认4/20) 已加进 `config.py`；`tier2._effective_proximity_pct`/`_should_skip_tier2` 改签名吃 `config`+`avg_atr`；config.yaml 里 ATR 块**默认注释掉**，所以部署即生效是**零行为变化**（仍固定 8%），定好 mult 再启用。
- **#21 优先级排序**：`run_daily_scan` 重构成"预取 bundle（throttle 移到这）→ `_ordered_run_plan`（held 先、观察票按距 target 最近、无 target 最后）→ 复用 bundle 跑 pipeline 不重抓"。`_run_ticker` 签名改吃 `_PlanEntry`，门控决策移到预取阶段。
- `scripts/calibrate_atr_proximity.py`（只读校准）、README×2、tests 全更新。
- **已 push c5316f9（机制）+ 2dfb078（启用 x3）**。校准（2026-06-16 VPS 实测 21 票）：固定8% 跳15/21（最激进）；**x3 跳9**、x4 跳7、x5+ 仅跳4（天花板20% 把 ATR%3-5 的票全顶到20，退化成"只跳>20%"）。**用户选 x3（要省钱）**：仍省，且不再错杀高波动近票（MOD 16.5% 但 ATR8.1%≈2 ATR日 → 该跑）。clamp 留代码默认 4/20。config.yaml 顶层 `atr_proximity_mult: 3.0` 已启用（min_price_proximity_pct: 8.0 作 ATR 缺数据时的 fallback 保留）。
- **⚠️ VPS config.yaml 与 origin 分叉**：仓库 config.yaml watchlist 是空注释，VPS 实时有 21 票（本机 commit）。auto-update `git pull` 靠**区域不重叠自动 merge**（watchlist 块 vs 底部门控块）——c5316f9 已验证能合进去。**部署后务必确认** `grep atr_proximity_mult ~/watchy/config.yaml` 真出现 `3.0`；若 merge 没带进来就手动加一行再 restart。
- **剩余 TODO**：①确认 auto-update 已 pull+restart 且 x3 生效；②下个工作日 Tier 2（11:30 UTC）看日志验证省钱 + #21 排序（held 先跑、观察票按距 target 排序）；③GitHub #21 验证后关。
