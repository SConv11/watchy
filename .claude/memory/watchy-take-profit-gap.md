---
name: watchy-take-profit-gap
description: 用户痛点=卖太晚赢家 round-trip；advisor 止盈条款补不了(系统性缺口,走#17/#26)；3.6 vs 3.5 受控 A/B 结论=混合、别为治止盈切模型
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f643c967-dcdd-4f5f-8361-42190c001e1e
  modified: 2026-07-22T15:45:53.047Z
---

# 用户交易痛点 & advisor 止盈缺口

用户自述（2026-07-22）：**「之前卖的都比较晚。往往都是有超额收益不卖、然后就跌回来了。」**
= 赢家冲高时没落袋，浮盈 round-trip 回吐。这是他最想让系统治的毛病。

## ✅ 已落地：advisor 止盈条款（commit f284518）
`ADVISOR_PROMPT` 新增 `TAKE-PROFIT / DON'T ROUND-TRIP A WINNER` 段（advisor.py:55-69）。
触发 = **浮盈可观（软锚 ~15%+）＋ 走势已 extended/动能衰竭（进阻力/目标区、MACD 走弱、
RSI 超买回落、低量反弹、剩余上行 vs 止损不划算）两条件叠加** → 倾向 TRIM。明确不是"涨 X% 就卖"；
**趋势还强/浮盈小则放行 HOLD**。改 Decision(→TRIM) 不改 `Target`(仍 entry-only)。

## ⚠️ 关键结论（2026-07-22 受控 A/B，n=5 + ANET 历史回放）——修正之前判断

**止盈条款目前补不了这个病，而且不是模型能治的——是系统性缺口。**

**ANET 铁证**（用户真实 round-trip 案例：7/13 冲 189、收 181、后回吐；均价 490/3≈163.33、3股、
账户~5900；用 `--position-file` 注入历史持仓 + 7/14 报告回放）：
- @181(+10.8%,锚下)：3.6=ADD / 3.5=ADD ——都想加仓。
- @189(+15.7%,锚上)：**3.6=ADD（还在高点追加！）/ 3.5=HOLD**（"avoid chasing at extended $189"、
  用 $169 止损"protect your 15.7% gain"）。
- **两个模型在任何价位都没 TRIM。** 原因：7/14 报告 Market Analyst 把 ANET 读成"强上升趋势、
  MACD 加速、站上所有均线"——**止盈条款按设计正确地没触发**（它明写强势 intact 趋势应 HOLD）。
  **分析在顶部还喊强，advisor 就永远慢半拍；round-trip 是之后才发生的。**

**3.6 vs 3.5 = 混合，各有失效模式**（同 prompt/持仓快照/low 档、only 模型变，5 票）：
| 票 | 情形 | 3.6 | 3.5 |
|---|---|---|---|
| GOOG | 17.7%超配+FCF崩+今日财报 | TRIM | TRIM（清晰局面都减）|
| AVGO | 13.2%超配、盘整 | TRIM | HOLD |
| NVDA | 10.6%超配、无催化 | HOLD | HOLD |
| SKHY | 2.8%低配、财报前 | ADD | HOLD |
| ANET@189 | 9.6%、+15.7%、extended顶 | **ADD(追顶)** | **HOLD(不追)** |

- **规律**：信号清晰时两个一致；只在**灰区**分歧，且 **3.6 无脑偏行动（双向）**——超配就减(AVGO)、
  见机会就加(SKHY)、**连 extended 顶都想加(ANET)**。3.5 更 inertial/谨慎、**不追顶**。
- **对用户 #1 痛点(round-trip)**：**3.6 追顶(ANET ADD@189)是减分项**——正是制造 round-trip 的行为。
  之前"3.6 更愿卖、可采用"的旧判断（n=2 旁证 AVGO/COHR）**据此撤回**：AVGO 的 TRIM 是集中度驱动，
  遇到真正的 extended 赢家(ANET)3.6 反而追顶。
- **成本**：3.6 在 AVGO/GOOG/NVDA 便宜 ~24%，但 ANET 两跑略贵——**因案而异、大致打平**，非稳定优势。

**live 现状（2026-07-22 定案）**：用户把 live `~/watchy_config/secrets.yaml` 的 model 改成 **gemini-3.5-flash**
（需 `systemctl restart watchy` 生效）→ 现在 **repo 默认 + live + thinking = 3.5-flash / low 三处一致**。
选 3.5 的理由：ANET 显示 **3.6 会追顶(extended 顶还 ADD)=对 round-trip 痛点减分**，3.5 不追顶更贴需求；
成本大致打平。**结论=别为"治止盈"去切模型**（ANET 证伪；止盈靠 #28 机械规则，与模型无关）。
之前"3.6 更愿卖、可采用"旧判断作废。

## 治本方向 → 已开专门 issue #28（2026-07-22）
止盈缺口的真解法**不是 prompt/模型/thinking**，是**机械止盈/移动止损**——跑在 **Tier 1**(30min 无 LLM 价格扫描)、
价格驱动、实时，不依赖 LLM 判断"动能衰竭"（分析在顶部还喊强时 LLM 必然慢半拍；且 LLM 判 extended 不一致
=ANET 同数据 3.5 HOLD/3.6 ADD 相反）。触发=**移动止损(峰值回落 X%/ATR 倍)** 或 **摸到 #16 derived_target_price
+浮盈过阈值→TRIM 一档**；hybrid=Tier1 机械抓回落→可选 LLM 定减多少。**3.5 在 ANET@189 自己够了个 $169 保护性
止损——这本能正可系统化。** = **#17 候选 A 的卖出侧实例**（#26 是买入侧 allocator，无关）。设计问题(state.db 存
峰值需 ALTER TABLE、arming 阈值/trail 宽度用 ATR、告警 vs 下单、防 whipsaw)全在 **#28** 正文。

## 工具/方法学备注（本次 session 修的坑）
`scripts/compare_gemini_models.py` / `compare_gemini_thinking.py` 之前有 **digest 还原 bug**：
把报告 `### Portfolio Manager` 段(=risk-debate judge_decision，生产放 `risk_assessment`)错塞进
`_decision_raw`、且丢 risk_assessment → 同模型同档 decision 都会翻。**已修**（aafe74b/1ace8b6：
正确映射 risk_assessment；`_decision_raw` 留空,因 .md 不存图的 final_trade_decision）。
**含义**：① 回退 3.5 当初那次 A/B 用的是脏 digest，依据存疑；② 离线工具**复刻不了 live 批次的逐决策**
（缺 final_trade_decision 块 + position 现拉），只适合**同一次运行内的受控 A/B**（模型vs模型、档vs档）。
新增 `--model`(thinking脚本)、`--position-file`(models脚本,注入历史持仓回放已卖出的票)。
详见 [[watchy-api-cost-baseline]]。
