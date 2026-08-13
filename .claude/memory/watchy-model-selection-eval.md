---
name: watchy-model-selection-eval
description: Watchy 选模型的评测方法 + 2026-08 AA 指数/价格实测；关键发现 V4-Pro(44) < V4-Flash(50)
metadata: 
  node_type: memory
  type: project
  originSessionId: 0c826df4-315c-43ad-9514-7423b3ce1f24
  modified: 2026-08-13T16:01:37.880Z
---

# Watchy LLM 选型 & 评测方法（讨论中，2026-08-02）

## 现状（2026-08-13 更新）
- **advisor = Gemini 3.5-flash，Tier1 与 Tier2 都是 thinking `low`**
  （3.6 用过一段、用户体感不佳已回退 3.5；Tier1 原 `off`，2026-08-13 上调到 `low`，理由见下）
- TradingAgents: deep_think = `deepseek-v4-pro`(RM/PM 两个节点), quick_think = `deepseek-v4-flash`，
  **两者都在 thinking `high`（DeepSeek 默认，watchy 不传参）；只有 high/max 两档，没有中间档**

## 🚨 2026-08-13 全面翻案：V4-Pro-0813 静默发布 + AA 子项数据推翻综合分结论

**V4-Pro-0813 于 2026-08-13 上午发布——无公告、无 changelog，只是价格表里冒出带日期快照。**
watchy 用浮动别名不锁版本（`pipeline_runner.py:29-30`）→ **VPS 的 RM/PM 当天就吃到新权重**。
下面「刷新前冻结 fixture」那条待办的窗口就此关闭。**但基线没丢**：`notify.py:237-241` 每次跑完都把
完整 markdown 报告当**文档附件发到 Telegram**，所以 pro-old 的 RM/PM 输出全在 Telegram 里（VPS
`~/watchy/reports/*.md` 是另一份）。

### 综合分说 Pro 赢，子项说 Gemini 赢 39 分 —— 以子项为准
| 模型 | AA Index | 8/02 时 |
|---|---|---|
| DeepSeek V4-Pro-0813 (max) | **53** | 44 |
| Gemini 3.6 Flash (high) | 52 | 50 |
| DeepSeek V4-Flash-0731 | 50 | 50 |
| Gemini 3.5 Flash (medium) | 47（估） | — |

**但 AA 指数构成变了**：现在 9 项含 GDPval-AA v2 / τ³-Banking / Terminal-Bench v2.1 / SciCode
——agentic+编码权重比 v4.1 更高，**对 watchy 的代表性反而更差**，53 vs 52 的 1 分可能全来自 Terminal-Bench。
**IFBench 已掉出综合分**（仍单独跑）→ **模型可以一边抬综合分、一边回退恰好会弄坏正则解析的那一项**。

### 三个关键子项实测（用户 OCR 自 AA，2026-08-13）
**AA-Omniscience 幻觉率（越低越好）**：Gemini 3.6F **56%** < 3.5F(medium/满) 62% < 3.5F(minimal) 74%
< V4-Pro 88% < V4-Pro(high) 89% ≈ V4-Flash(high) 89% < V4-Flash-0731(max) 92% < V4-Pro(max) 94%
< **V4-Pro-0813(max) 95%** ≈ V4-Flash 95% < V4-Flash(max) 96%。
**AA-LCR**：3.5F **81.0%** > 3.5F(med) 79.7% > **3.6F 79.0%** > V4-Pro-0813 75.3% > V4-Flash-0731 74.3%
> V4-Pro(max) 70.0% = V4-Flash(max) 70.0% > V4-Flash(high) 69.0% > V4-Pro(high) 67.0%
> 3.5F(minimal) 58.3% > V4-Pro(不思考) 49.7% > V4-Flash(不思考) 37.3%。
**IFBench**：V4-Flash(max) 79.2% > V4-Pro(max) 76.5% > 3.5F 76.3% > 3.5F(med) 74.6% > V4-Flash(high) 73.5%
> V4-Pro(high) 71.3% > 3.5F(minimal) 47.3% ≈ V4-Flash(不思考) 47.2% > V4-Pro(不思考) 45.8%。

### 由此定下的三个结论
1. **advisor 留 Gemini，不换 DeepSeek——已结案。** 幻觉 56/62% vs 95%，差 ~39 分，而 advisor 正是那个
   吐可编造数字的组件（`Take-Profit:` 限价、`Target:`）。**且涨价后省钱理由也没了**：Pro 非高峰 $0.66/$1.98
   vs Gemini 3.5F $1.50/$9.00，叠加 **Pro 很啰嗦（AA 指数跑了 130M 输出 token vs 3.6F 59M = 2.2×）**，
   实际只省 ~$38/年。19× 的老说法作废。**按架构和风险决策，不按省钱**（旧结论仍成立，但现在有两个理由）。
   ⚠️ 口径提醒：AA-Omniscience 是**闭卷参数化知识**测试；watchy 的分析师有工具、advisor 有 digest，
   都是有接地的，所以**绝对值夸大了风险（DeepSeek 88-96% 照样跑得好好的），能迁移的是排序**。
2. **3.6→3.5 回退是对的，且有数据支撑**：3.5 的 AA-LCR 81.0% > 3.6 的 79.0%，而 AA-LCR 正是 advisor
   的本职（综合 4 份分析师尾巴+risk+decision）。代价 = 3.5 输出 $9 vs 3.6 $7.50 且多 17% 输出 token
   ≈ 贵 40%（≈+¥240/年），为信得过的建议值这个钱。**这也解释了当初 n=5 A/B 为什么"混合"**：3.6 换来的
   是幻觉少 6 分、成本低，丢的是长文综合——不是全面变好。
3. **Tier1 advisor thinking `off`→`low`（2026-08-13 已改）**：`advisor.py:555` 把 `off` 映射成
   `thinkingLevel: minimal`，而 3.5F(minimal) 是**三项全场最差**（IFBench 47.3 / AA-LCR 58.3 / 幻觉 74%），
   偏偏 Tier1 跑的是**盘中止盈 zone-entry**（要吐可正则解析的 `Take-Profit:` + 限价 + 整股）。
   上调到 low 只花 ~$8/年。**关键洞察：档位比选模型更能改善幻觉**——3.5 从 minimal 调上去省 12 分，
   换 3.6 只省 6 分。

## ⚠️ thinking 关掉是断崖，不是斜坡（这条决定 #27 怎么做）

关掉 thinking 后三个模型一致暴跌：**IFBench 掉 29–32 分、AA-LCR 掉 23–37 分**（数字见上表）。
且 **DeepSeek 只有 high/max 两档，watchy 已在 high**（[[watchy-api-cost-baseline]]）→ **没有中间档可退**。

**#27（关 4 个 analyst 的 thinking）因此风险很高**：TradingAgents 四个 analyst 的 prompt 结尾都是同一句
"Make sure to append a Markdown table at the end of the report"（`analysts/fundamentals_analyst.py:28`、
`news_analyst.py:27`、`market_analyst.py:51`、`sentiment_analyst.py:160`），而 watchy 的
`advisor._analyst_summary_tail()` **正是锚定那张表**。这是教科书级 IFBench 失败点：
**末尾格式指令是指令遵循下降时最先被丢的东西**。丢了以后 `advisor.py:389` 静默退回**报告前 400 字**
（= 开头 prose，不是结论）→ 4 个分析师同时降级、日志无任何报错。
- **钱**：analyst thinking ≈ 账单 11% ≈ **$25–30/年**。**砍 2–3 只值守票收益相同、风险为零** → #27 不是钱在的地方。
- **要做就先测**：重放 ~20 份 analyst prompt（thinking disabled），数还有几份能被解析出结尾表格。20/20 才做。
- **无论如何先做的**：`ADVISOR_TAIL_FALLBACK` 警告已加（2026-08-13 commit），把静默失效变成可 grep，
  顺便给 #27 的重放测试提供**当前配置下的对照基线**（现在没人知道 fallback 率是不是 0）。
- **辩手（Bull/Bear/3 风险辩手）保留 thinking**（用户定）：对抗性判断节点，thinking 最可能真值回票价。

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

## ~~最大待办（有 deadline）~~ → **deadline 已过（2026-08-13 刷新落地），但基线在 Telegram 里没丢**
下面这段保留备查。实际结局：**没来得及冻结，但 `notify.py:237-241` 每跑一次就把完整报告作为文档发 Telegram**，
所以 pro-old 的 RM/PM 输出全在 Telegram 历史里 → pro-old vs pro-new 仍然做得成，只是要从 Telegram 捞。

**在 V4-Pro 早八月刷新前冻结 fixture + 把当前 pro 的 output 存盘**（只存 input 没用，别名一翻旧权重就取不回来）。
目的 = **测量这次刷新到底带来了什么**：翻版之后只能看到"输出不一样了"，没有 baseline 就分不清是变好还是只是变了。

- ~~现在跑 pro vs flash~~ **已放弃**：pro 几周内就被替换，A/B 一个将死的版本没意义，那段区间也就值 ~$5。
- 真正要建的比较是 **pro-old vs pro-new（同一批 fixture）**——冻结工作完全一样，只是问题换了。
- ~~顺带推论：**若刷新后 pro 明显超过 flash，最优解不是 RM/PM 降 flash，而是 pro 接管 advisor**~~
  **→ 已证伪（2026-08-13）**：刷新后 pro 只到 53 vs 3.6F 52（1 分 = 噪声，且档位不可比：pro 是 max
  effort、Gemini 是 high，而生产跑 low），够不上"明显超过"；更要命的是**幻觉 95% vs 56%**。
  省钱理由也被涨价+啰嗦度吃掉（只剩 ~$38/年）。**advisor 留 Gemini。**
  ⚠️ 但**刷新买到的确实是 AA-LCR（70.0→75.3）而不是诚实度（94→95）**——这恰好是 RM/PM 需要的、
  advisor 不需要的 → **现有分工（pro 管 RM/PM、Gemini 管 advisor）被这次刷新验证了，不是被威胁。**

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
