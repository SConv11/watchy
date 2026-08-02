---
name: watchy-model-selection-eval
description: Watchy 选模型的评测方法 + 2026-08 AA 指数/价格实测；关键发现 V4-Pro(44) < V4-Flash(50)
metadata: 
  node_type: memory
  type: project
  originSessionId: 0c826df4-315c-43ad-9514-7423b3ce1f24
  modified: 2026-08-02T07:29:10.933Z
---

# Watchy LLM 选型 & 评测方法（讨论中，2026-08-02）

## 现状
- advisor = Gemini 3.6-flash（Tier1 thinking off / Tier2 low）
- TradingAgents: deep_think = `deepseek-v4-pro`(RM/PM 两个节点), quick_think = `deepseek-v4-flash`
- 用户告知（当事实采纳）：**V4-Pro 将在 2026-08 上旬更新**

## 2026-08-02 实测数据（AA Intelligence Index v4.1）
- Gemini 3.6 Flash (high) = **50**（与它取代的 3.5 Flash 同分 → 解释了当初 3.6vs3.5 A/B 为何"混合"：本来就没差）
- DeepSeek V4-Flash-0731 (reasoning, max effort) = **50**
- DeepSeek V4-Pro (reasoning, max effort) = **44**
- AA 混合价：V4-Flash $0.06/1M vs Gemini 3.6 Flash $1.16/1M ≈ **19 倍**
- 官方 per-1M：V4-Flash $0.14/$0.28（cache hit $0.0028）; V4-Pro $0.435/$0.87; Gemini 3.6F $1.50/$7.50（缓存 $0.15）
- V4-Pro 强项是 SWE-bench 80.6%（编码），与 watchy 无关；AA v4.1 权重（HLE/GPQA-D/CritPt/AA-Omniscience/AA-LCR）更贴近本项目

🚨 **44 < 50 不能读成"pro 架构不如 flash"（此前的错误框架，已撤回）**：Pro 和 Flash 都是 2026-04-24 发布，
但 **Flash 已在 7/31 刷新成 0731，Pro 至今未刷新（AA 行名也是 flash 带日期后缀、pro 不带）**。
今天的对比 = 14 周旧模型 vs 2 天新模型，是版本时差不是架构结论。Pro 刷新后大概率反超 flash。

⚠️ **重要口径**：榜单分数都是 max effort。watchy 生产是 thinking off/low，**榜单的平局不能直接搬**，只能说明同档，胜负仍要自己的 harness 测。

## 最大待办（有 deadline）
**在 V4-Pro 早八月刷新前冻结 fixture + 把当前 pro 的 output 存盘**（只存 input 没用，别名一翻旧权重就取不回来）。
目的 = **测量这次刷新到底带来了什么**：翻版之后只能看到"输出不一样了"，没有 baseline 就分不清是变好还是只是变了。

- ~~现在跑 pro vs flash~~ **已放弃**：pro 几周内就被替换，A/B 一个将死的版本没意义，那段区间也就值 ~$5。
- 真正要建的比较是 **pro-old vs pro-new（同一批 fixture）**——冻结工作完全一样，只是问题换了。
- 顺带推论：**若刷新后 pro 明显超过 flash，最优解不是 RM/PM 降 flash，而是 pro 接管 advisor** —
  $0.435/$0.87 比 Gemini 3.6F 的 $1.50/$7.50 还便宜 ~3× 且更强，直接解决 Gemini 那笔 19× 的问题。

⚠️ **"更聪明" ≠ "对 watchy 更好"**：本地先例就是 Gemini 3.5→3.6，指数没动（都是 50）但行为变了，A/B 才会"混合"。
版本刷新即使不动综合分也会动行为，而**能弄坏你的子项不是上头条的那些**：为 agentic coding 调优的刷新可能抬综合分、
却回退 IFBench 式格式遵循 —— 那的失败形态不是建议变差，而是 `Take-Profit:` 正则静默匹配不到。

## 评测方法论（结论）
- 公榜只用来筛候选，不用来定胜负。AA 子项里只有 3 个相关：**AA-Omniscience**(幻觉，最重要——编造价位是最坏失败)、
  **IFBench**(指令遵循——`Take-Profit:`/`Target:`/整股都是正则抽取，跑格式=静默失效)、**AA-LCR**(长文综合→对应 RM/PM)。
  SciCode/Terminal-Bench/τ²/SWE-bench ≈ 无关。
- **arena.ai / LMArena 最没用**：测开放聊天人类偏好，奖励啰嗦对冲，与要的果断卖出结论相反。
- 金融 benchmark 只作过滤：BizFinBench.v2（最规范）、FinTrace（工具调用轨迹，对应分析师 tool loop）、
  XFinBench（校准用：最强纯文本模型 67.3% vs 人类专家 ~80% = 该品类天花板）。全都是 filings QA，没有"该不该卖"。
- 自家 harness 才是决胜器：`compare_rm_pm_models.py`(agree% + faithfulness + cost) / `compare_gemini_models.py`。
  三个要改：**n=5 是噪声(±20pp)，要 25-30**；**加止盈专属指标**（gain-gate 触发时有没有 `Take-Profit:` 行、
  限价 vs ATR 是否合理、整股整数、格式解析成功率）；**存 output 不只存 input**。
- 真正的 metric 没有榜单会给：**capture ratio = 已实现收益 ÷ 持仓期间峰值浮盈**，直接量化"卖太晚"（见 [[watchy-take-profit-gap]]、issue #17 close-the-loop）。

## advisor 换 DeepSeek 的取舍
智力理由已不成立（50 vs 50、19×）。**剩下的两条都不是智力**：
1. **相关性故障**：现在 Tier1（含盘中 zone-entry 卖出路径）不依赖 DeepSeek；合并后单一 API 成全系统 SPOF。可用 fallback 配置解决，不必付 19×。
2. **独立校验**：advisor 是给 pipeline 输出打分的，同族模型更容易顺着 pipeline 的框架走。真实但量级未测。
- 金额现实：advisor ≈ $0.5/天 ≈ $15/月，换过去 ≈ $1/月，省 ~$14/月。占比 65% 但绝对值小 → **按架构和风险决策，不按省钱**。

## 迁移坑（真换的话）
DeepSeek thinking **默认开且 high effort**，走 `extra_body` 里的 `thinking` 参数；thinking 模式下
**不支持 temperature/top_p/presence_penalty/frequency_penalty**；CoT 走 `reasoning_content` 字段而非 `content`。
Tier1 advisor 是刻意 thinking off 的 —— 不显式关掉会每 30 分钟静默付高 effort 推理钱，还丢采样参数。

## 其他核实（2026-08-02）
- **V4-Pro 官方未公告刷新**（用户另有信源，已按事实采纳）；V4-Flash 0731 已刷新；**R2 八月发布传闻被官方否认**；V5 无 model card/无路线图。
- watchy 用浮动别名 → 刷新零运维，但**风险是静默行为漂移**，需要 canary（见 [[watchy-api-cost-baseline]]）。
- CLAUDE.md 里"10:30 UTC 避开 DeepSeek 峰值计价"的理由**已过期**：V4 是平价，无分时档。排程本身仍合理。
- 便宜高智力已不止 DeepSeek：Qwen3.7 Flash $0.03/$0.13、MiniMax M3 ~$0.30/$1.20（信源打架，另有 $0.60/$2.40）、GLM-5.2 $1.40/$4.40、Kimi K2.6。
