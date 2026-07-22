---
name: watchy-take-profit-gap
description: 用户痛点=卖太晚赢家 round-trip；已加 advisor 止盈纪律 + 回退 3.5-flash（2026-07-22 落地）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f643c967-dcdd-4f5f-8361-42190c001e1e
  modified: 2026-07-22T13:51:51.719Z
---

# 用户交易痛点 & advisor 止盈缺口

## ✅ 已落地（2026-07-22，commit 已 push）
- **加止盈纪律**：`ADVISOR_PROMPT` 新增 `TAKE-PROFIT / DON'T ROUND-TRIP A WINNER` 段。
  触发 = **浮盈可观（软锚 ~15%+、非硬线）＋ 技术面已冲高衰竭（进阻力/目标区、MACD 走弱、
  RSI 超买/回落、低量反弹、剩余上行 vs 止损不划算）两条件叠加** → 倾向 TRIM 落袋。
  明确不是"涨 X% 就卖"；趋势还强/浮盈小则放行 HOLD。尊重既有 odd-lot / 集中度 guard。
  **改的是 Decision（→TRIM），不是 `Target` 字段——Target 仍 entry-only**（README 71-72 不变）。
  advisor 拿得到浮盈：`positions.render_position` 已输出 `Unrealized P&L: $X (+Y%)`（Schwab `_derive_pnl`）。
- **回退模型 3.6-flash → 3.5-flash**（用户定）：思路 = 保留 3.5 稳基线、靠显式规则拿果断，
  而非换个"到处都更爱卖"的模型。仓库默认已回退（advisor 兜底 + secrets.example + config 注释）；
  **live model 在 VPS `~/watchy_config/secrets.yaml` 的 `model:` 字段，须手动改 3.5-flash + 重启才生效**。
  3.5-flash 同用 `thinkingConfig.thinkingLevel`（low 档实测 in6024/think1997/$0.027 OK），thinking 配置不动。

用户自述（2026-07-22）：**「之前卖的都比较晚。往往都是有超额收益不卖、然后就跌回来了。」**
= 赢家冲高时没落袋，浮盈 round-trip 回吐。这是他最想让系统治的毛病。

**Why**：这不是模型笨，是**规则里就没有止盈这条纪律**。当前 `ADVISOR_PROMPT` 把 `Target`
字段明确定义成**入场/加仓价**，还写死一句 *"This is NOT a stop-loss and NOT a take-profit"*。
所以 advisor 天生只会说"哪里买"，**不会主动喊"该落袋/冲高减仓了"** → 用户体感"每次都卖晚"。

**How to apply**：
- 评估任何"要不要动仓 / 换模型 / 改 prompt"时，把**止盈倾向**当成用户的正向偏好——
  advisor **更愿意 TRIM/SELL into strength = 对齐用户需求**，不是缺点。
- 治本方向（待用户拍板，别擅自改）：给 advisor 加**止盈/浮盈保护逻辑**——持仓浮盈超过 X%
  且价触及分析给出的阻力/目标区时，倾向 TRIM 锁一部分超额收益。与 [[watchy-issue-plan]]
  的 #17（close-the-loop）、#26（组合级 allocator）同一路。换模型（3.6）只是治标。

## 关联：Gemini 3.6 vs 3.5 A/B 的旁证（n=2，2026-07-22）
`scripts/compare_gemini_models.py` 实测两票，**3.6 一致比 3.5 更果断卖**：
- AVGO：3.6=TRIM（13% 超配减到 1 股） vs 3.5=HOLD。
- COHR：3.6=SELL（趁反弹到阻力区整股清、基本面-FCF/83%稀释看空） vs 3.5=HOLD。
两票 3.6 都是"往强势里减/卖、落袋"，**方向正是用户要的**，是保留 3.6 升级的一个理由。
**Nuance**：这两票是"超配减仓 / 基本面止损"，**不是纯粹的赢家冲高回落**那一类；要坐实 3.6
真能治这个病，需再挑一只**当前浮盈不错且正撞阻力**的持仓跑一次验证。详见 [[watchy-api-cost-baseline]]。
