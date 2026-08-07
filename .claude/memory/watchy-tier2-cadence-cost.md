---
name: watchy-tier2-cadence-cost
description: V4-Flash-0731 重训导致 Tier2 时长×2/成本+40% 并跑过开盘；解法=分层 cadence tier2_days + 起跑 10:00 UTC；含 DeepSeek 高峰加价核实与被证伪的门控杠杆
metadata: 
  node_type: memory
  type: project
  originSessionId: 6180c108-90eb-4c62-a631-727109eaaa1a
  modified: 2026-08-07T15:37:11.216Z
---

# Tier 2 时长/成本回归与分层 cadence（2026-08-07 定案，commit `046b1cf`）

## 病因：DeepSeek V4-Flash-0731 重训（7/31 转正式，浮动别名自动生效）

**控制变量对比**（同名节点、同为 1 次调用，7/29–30 vs 8/3–5 的 TOKENCOST）：

| 模型层 | out | reason |
|---|---|---|
| flash 节点（Sentiment/Bull/Bear/Aggressive/Trader…） | **×2** | **×3–6** |
| pro 节点（Research Manager / Portfolio Manager） | 不变 | 不变 |

pro 是天然对照组 → 变量只有 flash 重训。后果：单票 $0.0272 → **$0.0382（+40%）**，
批次 7 月 1h20m–2h23m → 8 月 2h20m–**3h51m**。flash 输出里 **60% 是 reasoning token**。

⚠️ **已经跑过开盘**：10:00 UTC 起跑、开盘 13:30 UTC。最近 5 批 3 批迟到（8/3→10:20 ET 迟 50 分钟、
8/5→9:40、8/6→9:42），7 月一次都没有。**这比成本更值得当主要理由。**

## DeepSeek 定价核实（2026-08-07，deepseek.ai/pricing）

- 现价 V4-Flash $0.14/$0.0028/$0.28、V4-Pro $0.435/$0.003625/$0.87 —— 与 `token_tracker._PRICES`
  **完全一致**，记账是准的。
- 旧 off-peak **折扣**（16:30–00:30 UTC）属 V3/R1，随模型 **7/24 下线**一起没了。
- V4 宣布的是反向的**高峰加价 2×**，窗口 **UTC 01:00–04:00 & 06:00–10:00**（北京 09:00–12:00 &
  14:00–18:00），对 input/output/cache **全部**生效，**尚未启用**、无生效日期。
- ⚠️ **所以起跑时间没有提前空间**：08:00 UTC 会落在加价窗正中。10:00 是**最早的安全点**
  （窗口结束那一刻），只比原来的 10:30 早 30 分钟。CLAUDE.md 里 10:30 的原设计理由**没过期，反而更重要**。
- ✅ **但当前作业与加价窗口零重合**：Tier 2 跑 10:00→~12:00（周二至周五）/~13:51（周一），
  Tier 1 只在 13:30–20:00 美股时段跑，两者都在 01–04 / 06–10 之外。**加价即使生效也不涨钱**
  （一度写成"账单直接翻倍"，错，已撤回）。
- **正确定位**：加价约束的是"能不能提前起跑"这个**选项**，不是钱包 —— 也正是周一没法靠提前起跑
  救、只能接受迟到的根本原因。因此 **reasoning 开关的优先级不高**，理由只剩已发生的 +40% 与时长×2。
- 小尾巴：10:00 正好是窗口边界，若 DeepSeek 按闭区间算会擦到几秒（金额可忽略；要绝对保险挪 10:05）。

## ❌ 被证伪的杠杆：邻近门控（别再往这条路上想）

**持仓 13/18 = 72%，持仓永不门控。** gate-eligible 只有 MU/COHR/ETN/LRCX/CEG 共 5 只，
上限 ~50 分钟。**不是回归，是天花板本来就低。**（我一度判断"门控失效、修好能腰斩"，已撤回。）

## ✅ 解法：分层 cadence（`tier2_days`）

**关键洞察**：一次 4 分析师流水线 ≈ **$9.6/年/票**，与仓位大小无关 →
LUMN($63 仓位) = **15%/年**、EMR($159) = 6.0%、AVGO($852) = 1.1%。小仓位每天跑不划算。

- per-ticker `tier2_days: ["mon","wed","fri"]`，全局默认**不设 = 每个交易日**（不配则行为零变化）。
- **两条硬豁免**（cadence 只能延迟例行读，永远不能藏事）：
  1. 每周完整风控日（本周第一个交易日）
  2. **已进入止盈区的持仓**（机械判断、跑之前就能算、不花钱）
- 实际分组：每日 = AVGO/TSM/GOOG/AMZN/VRT/NVDA/**SKHY**（SKHY 是用户点名钉死）；
  一三五 = EMR/APH/NVT；二四 = ASML/VST/LUMN；观察票分摊 MU,COHR / ETN,LRCX / CEG。
- 效果：Tue–Fri **11–12 票 ≈ 2h**，10:00 起跑 → 8:00 ET 完成。
  **周一不受 cadence 影响、全量 18 票 ≈ 3h51m、用户明确接受迟到。**

## 重要事实纠正

**周一才是全量日，周日根本不跑**（CLAUDE.md 原文"Sunday runs the risk debate"是错的，已改）。
`daemon._is_tier2_day` = `is_trading_day()`（周末+NYSE 假日全跳）；全量 3-way risk debate 挂在
`market_calendar.is_weekly_full_risk_day()` = 本周第一个交易日（周一逢假顺延周二）。
印证：8/3（周一）TOKENCOST 标签 `risk1`，其余天 `risk0`。

## 搁置（有需要再捡）

- **DeepSeek reasoning/thinking 开关** —— 60% 输出是 reasoning，**最大单点杠杆**，但需先查 V4-Flash
  API 到底有没有这个参数。加价启用时优先级会飙升。
- **工作日砍 Fundamentals + News**（6/14 flash 调用、21% 成本）—— 会重开 #14 决议，最后手段。
- **并行跑票** —— 只治时间不治钱；2GB 机器常驻已 460–510MB，不建议。

## GitHub issue 状态（2026-08-07）

- **#28 已关闭**（completed）。收尾评论说明了**正文的 trailing-stop 方案已作废**、实际落地的是
  gain-gate + ATR runway + 预挂限价单，并列了 8/6–8/7 的实盘验证与碎股限制。
- **#29 新开**：`DeepSeek flash retrains silently drift token volume`。存证用 —— 记录症状、
  **用 pro 节点当对照组**的定位手法、以及"没有带日期 model id 可锁/可核"这个长期风险。
  里面留了三个未采取的选项（降 reasoning、砍 Fundamentals+News、漂移告警）。

相关：[[watchy-api-cost-baseline]] [[watchy-take-profit-gap]] [[watchy-tier2-risk-cadence]]
