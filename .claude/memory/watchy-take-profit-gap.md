---
name: watchy-take-profit-gap
description: 用户痛点=卖太晚赢家 round-trip；#28 已实现 LLM+预挂限价单方案(gain-gate floor 浮盈%+ATR runway,advisory-only 整股,Tier2 主+Tier1 盘中触发),opt-in 待上线验证；3.6 vs 3.5 A/B=混合、别为治止盈切模型
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f643c967-dcdd-4f5f-8361-42190c001e1e
  modified: 2026-07-27T09:53:50.867Z
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

## 治本方向 → issue #28（2026-07-22 开）→ **已实现（2026-07-23，LLM+限价单方案，非机械止损）**

**⚠️ 最终方案与 issue 正文/下面这段旧设想都不同——用户拍板走 LLM，别再想机械 trailing-stop。**

**落地设计（用户逐项拍板）**：机械部分缩成一个 **gain-gate 触发器**，LLM 仍主导，执行靠**预挂 sell-limit 单**
（限价单自己抓日内高点，所以不需要实时 trailing 代码，日更 cadence 就够）：
- **floor = 浮盈%**（默认 10%，`take_profit_floor_gain_pct` 可按票覆盖）触发进入止盈区；喂给 LLM 的是
  **机械事实**（浮盈越过 floor）当 ground truth，不让 LLM 判顶（绕开"分析喊强/extended 判断不一致"）。
- **runway = ATR**（离分析师上方位还剩几个 ATR → 贴顶就落袋/有空间就让它跑）；上方位从 digest 正则尽力提取，
  提不到就退化 `现价 + k×ATR` 限价。
- advisor 新增 **`Take-Profit:` 输出行** = 挂单价 + **整股**数（用户不玩碎股）。
- **主触发=日常 Tier 2**（持仓票在区内就注入指引）；**盘中触发=Tier 1 zone-entry**（浮盈盘中首次越 floor→
  只跑 advisor、复用 digest 不跑全 pipeline，cooldown 保护，靠新列 `state.prev_take_profit_zone` 做 on-entry 检测）。
- **advisory-only**：系统给价+股数，用户手动挂限价单。

**新增文件/改动**：`watchy/take_profit.py`（纯逻辑）、`watchy/digest_store.py`（复用最近 digest）、
`take_profit` config 段（opt-in `enabled:false` 出厂）、`notify.take_profit_alert`、advisor 注入+解析。
顺手修了 `config.py` 读 YAML 未指定编码的隐性 bug（Windows gbk 读非 ASCII 注释崩→改 `encoding="utf-8"`）。
6 个 commit（a815f33→20fb12d）已 push，357 tests green。

**上线状态（2026-07-27 核实）**：用户已在 **VPS `~/watchy/config.yaml` 直接改 `enabled: true`**，
自 **2026-07-23 起 live 跑了 4 天**，journal 里 take-profit 日志量很大（确在触发）。当时那个改动是
**VPS 本地 dirty（`git status` 显示 ` M config.yaml`）、没进 repo** → 下次 `git pull` 会在这行冲突。
**已收敛**：本地 commit `799c7f8` 把 repo 默认也改成 `enabled: true`（连带 README 配置表 + 本行说明 +
IMPLEMENTATION_PLAN 的 "opt-in" 措辞一起改），357 tests green。
**VPS 收敛步骤**（必须等本地 push 之后再跑，否则会把 live 的 flip 丢掉、止盈静默）：
`cd ~/watchy && git checkout -- config.yaml && git pull`。
⚠️ push/重启避开 10:30–12:00 UTC Tier-2 窗口（auto-update timer 会重启 daemon）。
**2026-07-27 验证结论：4 天零触发 = 正确行为，不是 bug**。持仓最高浮盈仅 EMR +7.0% / SKHY +6.2% /
NVDA +4.6%，全都够不到 floor 10%（Schwab live 正常、cost basis 正常）。**注意：journal 里根本没有
`Take-Profit:` 字样**——那是 LLM 输出行、只进 Telegram；真正的 journal 标记是
`take-profit zone active for X: gain=..` (advisor.py:151, INFO) 和 `Take-profit zone entered` (tier1.py:269)。

**受控 dry-run 验证通过（EMR，floor 临时降 5% 且只改内存、不动 live config）**：gate 触发 → 正则从
7/24 digest 提到 `upside=185.0` → runway 9.8 ATR(>far 2.5) → 走 stretch 3×ATR → 输出
`take_profit: sell 1 share at 157.44`(整股、在市价上方)、decision=HOLD。一次 advisor 调用 $0.0112。
**核心链路全对。** dry-run 脚本模板见本条历史（load_config→改 c.take_profit.floor_gain_pct→
compute_indicators→load_digest→get_advice）；注意 IndicatorBundle 字段是 `current_price` 不是 `price`。

**🐛 发现真 bug（待修）：限价锚定价源不一致**。`advisor.py:144-148` 有 bundle 时 `price =
indicator_bundle.current_price`（yfinance，EMR=145.33），但 gain 来自 Schwab（live last=148.72）——
差 $3.40≈0.84 ATR。结果限价 157.44 而非 160.84，**偏低=更容易成交=比预期卖便宜**，对"别卖太便宜"
这个目标方向性错误。修法：优先 `pos.current_price`(live)，bundle 当 fallback。

**#28 仍 open**：核心已验证，但 **Tier 1 zone-entry 转换 + `notify.take_profit_alert` 仍未实跑过**
（要等真有票越 10%，或专门造一次）。

**未做（deferred）**：机械 trailing-stop（撤销）；一等公民阻力位提取（现正则尽力）；触发时的 full-pipeline hybrid；
Schwab 自动下单。= **#17 候选 A 卖出侧实例**（#26 买入侧无关）。

---
**（作废的旧设想，留档对比）** 曾想：机械止盈/移动止损跑 Tier 1、峰值回落 X%/ATR 倍触发、摸 #16 derived_target
+浮盈阈值→TRIM。**已被 LLM+限价方案取代**——关键洞察=限价单预挂就能抓日内高点，不必实时 trailing；且
#16 `derived_target` 是**入场价**（对持仓赢家在现价下方，方向错），当止盈天花板用不了。

## 工具/方法学备注（本次 session 修的坑）
`scripts/compare_gemini_models.py` / `compare_gemini_thinking.py` 之前有 **digest 还原 bug**：
把报告 `### Portfolio Manager` 段(=risk-debate judge_decision，生产放 `risk_assessment`)错塞进
`_decision_raw`、且丢 risk_assessment → 同模型同档 decision 都会翻。**已修**（aafe74b/1ace8b6：
正确映射 risk_assessment；`_decision_raw` 留空,因 .md 不存图的 final_trade_decision）。
**含义**：① 回退 3.5 当初那次 A/B 用的是脏 digest，依据存疑；② 离线工具**复刻不了 live 批次的逐决策**
（缺 final_trade_decision 块 + position 现拉），只适合**同一次运行内的受控 A/B**（模型vs模型、档vs档）。
新增 `--model`(thinking脚本)、`--position-file`(models脚本,注入历史持仓回放已卖出的票)。
详见 [[watchy-api-cost-baseline]]。
