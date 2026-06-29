---
name: watchy-api-cost-baseline
description: Watchy 每日 LLM API 成本基线与模型配置（DeepSeek V4 + Gemini），CNY/USD 分开记
metadata: 
  node_type: memory
  type: project
  originSessionId: 59228ea1-72b5-4746-be2d-7cf8847d06b0
---

# Watchy LLM API 成本基线

首个完整交易日观测：**2026-06-09（周二，美东交易日）**。

## 当前模型配置
- **Tier 2（TradingAgents pipeline，`watchy/pipeline_runner.py`）**：provider=DeepSeek
  - deep_think_llm = `deepseek-v4-pro`（Research Manager / PM）
  - quick_think_llm = `deepseek-v4-flash`（analysts / debaters / trader）
  - 调度：每日 `11:30 UTC` 跑一次（周六跳过）
- **Advisor（持仓建议合成，`watchy/advisor.py`）**：provider=Gemini，model=`gemini-3.5-flash`（VPS 实跑用的是 3.5-flash，确认于 2026-06-10；`secrets.example.yaml` 里的 2.5-flash 只是示例值）

## 成本基线（2026-06-09，单交易日）
**CNY 和 USD 分开记，不换算混算：**
- **Gemini**：**$0.5 USD**
- **DeepSeek**：**¥4 CNY**

月度估算（~21 交易日/月）：
- Gemini ≈ **$10.5 USD/月**
- DeepSeek ≈ **¥84 CNY/月**

→ 单日 ~$1 量级，健康，无异常烧钱。以后对账若显著偏离此基线再排查。

## 成本连降三天 = 门控自举 + Tier1 触发下降（实锤于 2026-06-13，已与 Gemini dashboard 交叉验证）
三天成本：Gemini $0.494→$0.360→$0.294，DeepSeek ¥3.96→¥2.91→¥2.38（均约 −40%）。

**从下载的全量 journal 重建三天账，每天都与 Gemini dashboard 请求数精确吻合：**
| 日期 | Tier2进入 | 门控跳过 | Tier2跑 | Tier1触发 | 总工作单元=advisor=Gemini |
|---|---|---|---|---|---|
| 6/10 | 17 | **0** | 17 | 6 | 17+6 = **23** ✓ |
| 6/11 | 17 | **3** | 14 | 1 | 14+1 = **15** ✓ |
| 6/12 | 17 | **5** | 12 | 0 | 12+0 = **12** ✓ |

23/15/12 = dashboard 实际值。结论：
- **8% 门控（[[watchy-pending-enable-tier2-gate]]）在正常工作，是降本主因之一。** 跳过数 **0→3→5 逐日爬升**，
  正是 #15 设计的自举：`derived_target_price` 头几天才 seed 上，seed 上后门控才开始咬。6/12 跳的 5 个
  （MOD/VRT/CEG/APH/SOXX）全是**值守票冲到各自 entry 目标价上方 >8%** 的动量股——门控正确停掉"现价不会买"的票。
- **每个"工作单元" = 1 次 DeepSeek pipeline + 1 次 Gemini advisor**（`get_advice` 无条件调，advisor.py:136 Tier2 / tier1.py Tier1）。
  所以两家成本**天然 lockstep**，跳一个票同时省两家。
- **第二股力：Tier1 触发 6→1→0**（行情转淡 + 6/10 砍掉 `volume_anomaly_moderate` 噪声信号）。

**⚠️ 排查教训（重要）**：最早用一次性 `journalctl --since "$day 06:00" | grep -c "weekday gate"` 拼凑的统计
**误报"每天 0 skip"**（真实 0/3/5），一路把结论带偏成"门控没用 / 降本另有其因"。**下载全量日志落盘对账**才对上 dashboard。
教训：成本/门控对账**别信一次性 journalctl 拼凑命令，要导出全量日志核对，并与厂商 dashboard 交叉验证**。

（旁注：`sqlite3 ... ticker_state` 里 **TSLA 的 derived_target_price 为 NULL**，没 seed 成功——留意 advisor 对 TSLA 的 Target 是否没解析出；TSLA target=None 时 `proximity.is_outside_proximity` 返回 False → 永远跑，不被门控。）

## 账单时区（对账关键，见 [[watchy-vps-deployment]]）
- **Gemini 按太平洋时间 (PT) 日切**（00:00 PT 重置；6月夏令时 PDT=UTC−7）
- **DeepSeek 按 UTC 日切**（其历史 off-peak 折扣窗写成 16:30–00:30 UTC，证明时间核算基于 UTC）
- 两家 dashboard 的日期都**等于美东交易日同一天**（因为 Tier1 盘中 13:30–20:00 UTC、Tier2 11:30 UTC，都远离两个时区的 00:00 日界线，不会跨日切割）。
- ⚠️ **对账用美东日期 / 各自 dashboard 的日期，别用北京日期（CST UTC+8）**——北京日历会错位一天。
- DeepSeek Usage 页可**按月 Export CSV**（逐 Key 明细），比看图表准。

## 组件级 DeepSeek 成本拆分（TOKENCOST,commit 868c571,2026-06-13）
上面的账只到"每票一次 pipeline"粒度;要看**钱花在哪个 graph 节点**(哪个 analyst/debater/manager),
加了 `watchy/token_tracker.py`:一个 LangChain callback,按 **model**(pro/flash)+ **node** 双维度
累计 token,每次 pipeline 跑完打一行可 grep 的 INFO 日志:
`TOKENCOST <ticker> [<analysts>|risk<N>] usd=.. models={pro/flash..} nodes={..}`。
- `usd=` 是 DeepSeek 估算成本的 **USD 代理值**(看占比,不是真实账单——真实按 CNY,见上)。异常安全,坏了只丢测量不挂 pipeline。
- 收集:Tier 2 跑完后 `journalctl -u watchy --since today | grep TOKENCOST`(对账别信一次性拼凑,见上排查教训,要导出全量)。
- **状态:已部署并实测**(VPS 自 2026-06-14 起跑带 TOKENCOST 的代码;见下首份实测)。
- ⚠️ 新票无 `derived_target_price` 种子 → 8% 门控头一两天不咬 → TOKENCOST 行数/总额头几天偏高,几天后自举落稳态,别误判回归。

### 首份实测拆解 — 2026-06-14 周日批(完整版:4 分析师 + 3 路风险辩论 `...|risk1`)
跑了 **16 票**(watchlist 17,**COHR 缺**——疑在批次开头被 grep 窗口切掉或那次 run 报错,待查)。
- **批次总额 $0.538 ≈ ¥3.9**,均 **$0.0336/票**(区间 $0.029 ETN–$0.038 AVGO,方差极小 → 成本由 pipeline 结构决定,不是某只票)。¥3.9 对得上"¥4/天"基线。⚠️ 这是**周日上限**(全跑 + 风险辩论);工作日无风险辩论 + 8% 门控跳票 → 明显更便宜,**待补工作日实测**。
- **模型层:flash 70.6% / pro 29.4%。** pro(deep_think)**仅 2–3 次调用/票却吃 ~30% 钱**(单次 ~$0.0048,是 flash ~$0.0014 的 3.5 倍),集中在 **Research Manager + Portfolio Manager**(终审走深推理)。flash 调用量大但靠缓存压住(Market Analyst 输入 8万 tok、缓存命中 ~64%)。
- **节点排名(16 票合计 / 占比):** Portfolio Manager $0.097/**18.1%**(仅 1 调用但 pro+长输出,单一最贵)> Market Analyst $0.075/14.0%(4–6 次工具调用回灌超大输入)> Research Manager $0.061/11.3%(pro)> Fundamentals $0.055/10.2% > Neutral $0.042 > Bear $0.042 > Conservative $0.037 > Bull $0.033 > Aggressive $0.032 > Sentiment $0.027 > News $0.026(NVDA/HUBB 偶发 5 调用飙高)> Trader $0.005 > unknown $0.005(~1% 未归类)。
- **功能归组(降本杠杆):** 两个 Manager(pro)29.4% | 4 分析师 34% | **风险辩论(激进+保守+中性)20.6%——周日专属,周成本非日成本** | 多空辩论 13.9% | Trader+unknown 2%。
- **可砍处(按性价比):** ①真正杠杆是 **8% 邻近门控**(工作日整票跳过)——已启用 [[watchy-pending-enable-tier2-gate]]。②大降本就把 **Research Manager 降到 flash**(最大单一结构杠杆,但终审质量风险最高,PM 建议保 pro)。③Market Analyst 减抓取指标数/缩回看窗(纯输入侧,不碰质量)。④风险辩论一周才一次,动它收益有限。

### 工作日实测补齐 — 2026-06-15(周一,`...|risk0`,无风险辩论)
- **B 工作日全量 16 票:合计 $0.436,均 $0.0272/票**($0.023–0.033)。vs 周日 $0.0336 → **同票配对平均 −$0.0064/票(−19%)**(最大降 EMR −0.0106/AVGO −0.0097/NVDA −0.0083)。
- **省的钱几乎全在 flash 侧**:`risk0` 砍掉 **Conservative + Neutral** 两个风险分析师(各 ~$0.002)+ 缩 RM/PM 上下文。**注意 Aggressive 在 risk0 仍保留**——"无风险辩论"是砍 2 个不是 3 个。
- **pro 占比反升(地板效应):** AMZN 周日 pro 30% → 工作日 34%。flash 随分析师减少而降,**pro(RM+PM)是固定地板**(2 调用不变)→ 越省 pro 占比越高,印证"降 RM 到 flash"是最大结构杠杆。
- **盘中 2 分析师重扫 `[market+social]|risk0` ≈ 半价**($0.015–0.018/次,全量的一半)。一票一天可被重扫多次(6/15:KLAC×4、LRCX×3、AMAT×2)→ **工作日真实账单里易忽略的累加项**。
  - **已上盖子(#23,commit f906a5c,2026-06-19):** Tier 1 每票每 UTC 日重扫次数上限 `max_tier1_pipelines_per_day`(全局+按票覆盖,config.yaml 出厂 **2**)。每次信号触发原本只受**每信号冷却**约束,所以一票一天触发多种信号会叠加多次付费 pipeline+advisor;cap 数 launched runs(run_history tier1,UTC 日切),超限仍 log_signal+推送 `Signal Fired (rescan capped)` 但跳过 pipeline。**持仓票不特殊豁免**(避免 Tier1 耦合持仓源),要全覆盖就按票设高/删 key。Tier 2 定时不受影响。这是用户选的降本杠杆(否决了再收紧门控,因刚做完 6/16 ATR×3 校准)。
- ⚠️ **异常值:** `6/15 14:09 EMR [market+social]=$0.0292`(其它重扫的 ~2 倍),根因单个 **Market Analyst in=193,073 tok / 单节点 $0.0141** 一次失控大输入回灌;偶发——根因+修法见 issue #20。

### TradingAgents 调优 → 暂不修,记 issue #20(2026-06-16)
源码在 vendored `~/TradingAgents`(upstream TauricResearch/main,已带未追踪本地补丁)→ 改它先要追踪机制(`patches/tradingagents.patch` 或 fork)。两件已查清根因+写好 patch,#20 待做:
- **A. risk0 风险位是 Aggressive 不是 Neutral(偏向 bug,非成本):** 图拓扑必然——`setup.py` Trader→Aggressive 无条件边 + 门控只在首发言后判,risk0(max_risk=0)下 Aggressive 跑一次直进 PM。**决定换 Neutral**(同价、去偏向、PM prompt 仍连贯;删掉会让 PM 的"synthesize the debate" 收到空 history → 退化)。Neutral debator 本就处理"首位发言"。周日 risk1 不变。
- **B. Market Analyst 降上下文(成本):** 指标恒用 5y 缓存算(`stockstats_utils.load_ohlcv:64`)→ look_back/价格窗都是**显示窗,砍它不坏 200_sma**。做 A(夹 get_stock_data≤120d,封死 EMR 193k 爆炸)+ B(get_indicators look_back 30→14),hold D(指标 8→5 动分析广度),C 可选(去周末 N/A 行)。
- ⚠️ 部署:只改本机笔记本没用(daemon 在 VPS 跑),且 upstream pull 会覆盖未追踪改动;VPS 上线避开 Tier-2 窗口(~11:30–13:00 UTC)。

## ⚠️ DeepSeek 高峰时段价格翻倍（2026-06-29 用户告知，新政策）
- **高峰窗（北京时间 UTC+8，无夏令时）：每日 09:00–12:00 和 14:00–18:00，该时段单价 ×2。**
- 换算到 UTC（账单/调度都按 UTC，见下时区节）：**01:00–04:00 UTC 和 06:00–10:00 UTC**。
- **对 Watchy 影响 ≈ 0**——所有 DeepSeek 调用天然落在峰外：
  - Tier 2 定时批：`11:30 UTC` 起跑（~11:30–13:00 UTC 窗 = 北京 19:30–21:00）→ 峰外（18:00 之后）。
  - Tier 1 盘中重扫：绑美东盘时 ~13:30–20:00 UTC（夏）/14:30–21:00 UTC（冬）→ 都在 06:00–10:00 UTC 峰窗之后，峰外。
- **唯一护栏：别把 `tier2_time_utc`（全局默认 11:30，或按票覆盖）挪进 01:00–04:00 / 06:00–10:00 UTC。**
  config.yaml:43 的示例 `"14:30"` 安全（14:30 UTC=峰外）；但形如 `08:00`/`02:00` 会正中峰窗、该票成本翻倍。
- （Gemini advisor 是另一家 provider，与 DeepSeek 时段定价无关。）

## DeepSeek V4 已无 off-peak 折扣
- off-peak 折扣窗（16:30–00:30 UTC，V3 五折 / R1 2.5 折）**只覆盖旧的 V3/R1**。
- **V4-Pro 把降价做成永久价**，替代了时段折扣；官方 pricing 页对 V4 无任何时段折扣字样。
- 结论：**不要再为省钱把 Tier 2 挪进 off-peak**，对 V4 无效（但见上：现在有"避开高峰加价"的反向理由——别让调度漂进峰窗）。
- V4 官方价（per 1M tokens）：
  - V4-Flash：input cache-miss $0.14 / cache-hit $0.0028 / output $0.28
  - V4-Pro：input cache-miss $0.435 / cache-hit $0.003625 / output $0.87
