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
