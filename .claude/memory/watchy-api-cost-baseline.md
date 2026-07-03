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

## DeepSeek 前缀缓存：逐节点命中实测 + 「缓存这条路已到头」结论（2026-06-30）
DeepSeek 是**自动前缀缓存**（64-token 块，只有「同一段前缀被重复发送且仍在缓存」才命中）。TOKENCOST 行里
逐节点记了 `cache`/`in`，从一整批 6/29 工作日批（15 票 `risk0`）算出逐节点命中率：
- ✅ **Market Analyst ~65% / Fundamentals ~42% / News ~40%** —— 靠**工具循环内几秒重复发大前缀**自缓存（不是因为静态在前，而是又大又新鲜）。
- **pro 单发节点 PM/RM/Trader**：只拿到 512 token 缓存地板（结构化输出 schema），单发无法跨票缓存。
- ❌ **4 个单发 flash 节点 Aggressive / Bear / Bull / Sentiment = 精确 0% 命中**，合计 ~619k token 全按 miss 满价
  = **$0.087/批 ≈ 占整批 $0.39 的 22%**。根因：单发（无工具循环重复）+ prompt 早段就出现按票变化内容；
  且 `bull_researcher.py:23` **开头有 ~250 静态 token 却仍 0%** → 证明**小静态前缀撑不住**（写入门槛/被中间几十个大调用 LRU 挤掉）。
  反证：盘中同一只 ETN 的 Sentiment `cache=5120/in=5174≈99%`（1.5h 内重扫同票）→ 机制没坏，纯跨票前缀被破。
- **唯一可能有效的缓存杠杆**：同票 4 份分析师报告（~8–10k token）被 Bull/Bear/RM/风险者/PM 消费 5–6 次/票（~1 分钟内）。
  现各自嵌在不同指令后 → 前缀第 1 token 就分叉。若重构成**所有消费者共享的、放最前面的同一段报告块**（指令挪到报告后），
  消费者 2..N 可命中。**上限 ~17%（现实 ~10%）= 省 ~$0.04–0.066/天 ≈ $1–2/月**。
- **结论：不值得做。** 整批本就 $0.4/天，为 $1–2/月去改 6 个 vendored agent 文件 + 冒「指令置于数据后」的质量风险 +
  每次 upstream pull 重打补丁，ROI 太低。**缓存大头已被工具循环自动吃掉，剩下要么物理不可缓存（每票独有数据），要么改造不划算。**
  省钱继续走 ①8%/ATR×3 门控（整票跳过，最狠，已启用）②#20 B 缩 Market Analyst 输入（见下，纯砍输入不碰质量 + 修 EMR bug）。

### #20 B 参数缩窗的负面影响评估（2026-06-30，确认很小）
指标值**永远用 5y 全量缓存算**（`stockstats_utils.load_ohlcv` 载 5y → `get_stock_stats` 取 curr_date 当天值），
`look_back_days` 与 `get_stock_data` 日期范围**都不参与计算，只决定喂给 LLM 看多少行**：
- **`get_indicators` look_back 30→14**：指标值零损失（200_sma 仍真 200 日）。只缩「LLM 看到的近期轨迹」30→14 天。
  真实损失=月级叙事变薄、**慢成型形态（3–4 周金叉/多周背离）历史轨迹不易肉眼读出**（当前值仍在）。多数可操作信号活在近 1–2 周，14 天够。**风险低**。⚠️ 改默认值=软上限，LLM 仍可主动传更大值。
- **`get_stock_data` 夹 ≤120d**：原始日线表封顶 ~6 个月。损失=LLM 不能再肉眼看 >6mo 原始 K 线 / 从原始表推 52 周高低点；
  但长期趋势靠 200_sma（5y 算）不丢。**这是硬夹（服务端强制）**，正是它封死 EMR 193k 失控大输入——最大价值在此。**风险低**。
- 一句话：两者都只缩「可见窗」不碰「计算质量」，代价=长周期/月级 context 从原始数据退到指标摘要，对日级扫描可接受。

## 2026-07-03 降本调查 + thinking 发现（本轮）

**Tier1 vs Tier2 实测拆分（VPS journal，10 天，usd 是 DeepSeek 相对代理值）**：判别=TOKENCOST label 里带 `fundamentals`→Tier2，否则 Tier1。
- **Tier2 工作日**(`...+fundamentals|risk0`) **72%** / Tier2 每周首日(`|risk1`) 13% / **Tier1 信号升级**(`market+social|risk0`) **仅 14%**。
- **反直觉结论**：用户对 Tier1 信任度低、想砍它，但它只占 14%；真正大头是 Tier2 工作日。且 Tier1 也在用 pro（RM+PM 每条 pipeline 都跑，Tier1 里 pro=$0.22）。
- 拆分脚本：`journalctl -u watchy --since "10 days ago" | grep TOKENCOST | python3`（正则要锚定 `TOKENCOST\s+\S+\s+\[...\]`，别抓到行首 `python[PID]` 的方括号）。按 `models=`/`nodes=` JSON 还能出 pro/flash 与节点级拆分：Market Analyst 20%、PM 15.6%、RM 13.8%、Fundamentals 10.8%；pro 合计 29.4%（=PM+RM 两个 deep 节点）。

**thinking 关键事实（查 TradingAgents 源 + api-docs.deepseek.com）**：
- `deepseek-v4-pro` / `deepseek-v4-flash` **两个都是思考模型**（TA `capabilities.py` 里都 `_DEEPSEEK_THINKING`、`requires_reasoning_content_roundtrip=True`）。所以 **thinking 是每个节点都在烧**（不只 RM/PM），reasoning token 按 output 计费（pro out $0.87/1M、flash $0.28/1M）。
- **V4 thinking 可开关**：请求体 `"thinking":{"type":"enabled"/"disabled"}`。旧 `deepseek-chat`/`deepseek-reasoner`=V4 的非思考/思考模式，**2026-07-24 弃用**。→ 只谈 v4-pro/flash 的开关即可，不退旧模型。
- **现状**：TA 的 `DeepSeekChatOpenAI` 没传 thinking 参数 → 全默认 thinking=ON。关它需要给请求加 `extra_body={"thinking":{"type":"disabled"}}`（langchain ChatOpenAI 的 `extra_body`），这落在 TA 客户端（vendored）或直接构造 LLM 时。
- 节点映射（TA `graph/setup.py`）：**deep(pro)=Research Manager + Portfolio Manager**；quick(flash)=4 分析师+多空+trader+3 风险辩手。

**本轮交付的两个工具**：
- **① `token_tracker` 拆 reasoning token**（已并入）：`_extract_usage` 返回 5 元组多了 reasoning，TOKENCOST 的 models/nodes JSON 多 `reason=` 字段（是 out 的子集）。跑一两批就能看 thinking 占每个节点多少钱。
- **② `scripts/compare_rm_pm_models.py`**（#18 落地，离线、需 DEEPSEEK_API_KEY、不进 daemon）：从 `~/watchy/reports/*.md` fixture 复现 RM/PM 两节点，跑 **pro vs flash**（**RM/PM 只考虑 thinking 开**，用户定；thinking 开关这条轴留给 quick 节点另说），输出 rating 一致性 / 价位忠实度 / 成本 / 延迟，基线=pro(=生产)。**用 trading pyenv python 跑**。fidelity 注意：debate history 由报告分段拼回（非原始交织），两格一致所以相对比较有效。
- **③ Gemini advisor thinking 打开**（用户定）：原来 `thinkingBudget:0`（关）。改成 `LLMConfig.gemini_thinking_budget`（默认 -1 动态开，0 关，>0 固定上限），且 thinking 开时 `_call_gemini` 给可见答案加 `_GEMINI_THINK_HEADROOM=2048` 额度（thinking 与 maxOutputTokens 共享，不加会截断你每天读的建议）；响应解析跳过 thought part。secrets.yaml 可加 `gemini_thinking_budget` 覆盖。
  - **⚠️ 待测(TODO)：thinking 该不该开，要 A/B 实测再定默认值** —— 建 advisor 对比脚本(=#18 原始范围：advisor 的 model × 输入保真度 × thinking 网格；compare_rm_pm_models 只覆盖了 RM/PM，没覆盖 advisor)。测：thinking 开是否真提升建议质量(决策一致性/价位忠实度) vs 增加的成本+延迟。开着是当前默认，但**未经验证**。

## Gemini(advisor)成本怎么降（本轮查清）

- **调用量**：`get_advice`（Gemini）在 **Tier1 升级后 + 每次 Tier2** 都调一次（`tier1.py:139` / `tier2.py:204`）→ ≈每条 pipeline 一次 Gemini 调用（~15/天）。
- **模型 = Gemini 3.5 Flash，价格很贵**（用户给）：input **$1.5/1M**、output(含 thinking) **$9/1M**。对比 DeepSeek flash out $0.28 / pro out $0.87——**Gemini 输出比 DeepSeek pro 贵 ~10x**。所以 ③ 开 thinking(thinking 按 $9/1M 计) 可能显著加钱，**更该先测再默认开**。
- **✅ 已加 Gemini 成本日志(本轮 ③④批,未提交)**：`_call_gemini` 现在读 `usageMetadata` 打 `GEMINICOST <ticker> model= in= out= think= usd=` 行（`think`=`thoughtsTokenCount`，thinking 单独可见；`usd` 用上面价格估算，token 数精确）。之前 Gemini 完全没仪表，全靠 Google 后台。grep `GEMINICOST` 即可按票看 advisor 成本 + thinking 占比。
- **输入大头**：`advisor._format_analysis` 把 **4 份分析师全文**（market/sentiment/news/fundamentals，来自 `_reports`）+ risk + 完整 decision 全塞进 prompt → 每次 advisor 调用输入 ~几 k–10k token。这是 Gemini 成本主因（¥/$ 首日 Gemini≈$0.5/天）。
- **降本杠杆(排序)**：
  1. **截断输入(=#18 Axis B，最大杠杆)——✅ 已实现(用户定，本轮)**：`advisor._format_analysis` **不再喂 4 份分析师全文 prose**，改喂 digest = Final Decision + Risk Assessment + Trader Plan(含具体入场/止损/目标价) + **每份分析师的"总结尾巴"** + SEPA stage。省 ~70% 输入 token。ADVISOR_PROMPT 开头改成"condensed analysis summary"。测试 `TestAnalystSummaryTail`/`TestFormatAnalysis`。
     - **"总结尾巴"= 从报告最后一张 Markdown 表到报告结尾**(`_analyst_summary_tail()`，锚定最后一段 ≥2 行的 `|` 块，取到 EOF)。这样**表 + 表后面的结论**都进(Market 的 TRANSACTION PROPOSAL+Reasoning、News 的 preliminary assessment、Fundamentals 的 💡FINAL ASSESSMENT——都是分析师可执行的"为什么"，advisor 写理由用得上)；丢掉的是表**之前**那一大坨分析 prose(token 大头)。副作用：Sentiment 的 disclaimer 也会带进来(短，不管)。无表则退回报告前 400 字。
     - 报告解析陷阱(踩过)：分析师报告**内部有自己的 `##/###` 标题**(`## KEY METRICS SUMMARY TABLE`、`### Long-Term Trend`)。**运行时 `_format_analysis` 用 `_reports` 完整原文、不受影响**；但离线脚本/验证若按"所有 `##/###`"切会把报告碎片化(→ 抽不到表，曾误报命中率0)。正确解析只按 `### <已知agent名>` + 罗马分隔 `## II.` 切——`compare_rm_pm_models.py` 的 `parse_report` 已据此修正(否则 RM/PM 的辩论 history 会被截断)。
     - ⚠️ 忠实度(价位是否还准)仍建议随 #18 一起 A/B 验证。
  2. **换更便宜模型**：`gemini-2.5-flash-lite` / `gemini-3.1-flash-lite`。
  3. **thinking 关**（与 ③ 相反——③ 开 thinking 是**增**成本，故 ③ 必须先测值不值）。
  4. **少调**：verdict 未变的票跳过 advisor（省头小）。
  5. 输出已封顶 1024（thinking 开时 +2048 headroom）。
- 待跑：用户在 VPS 跑 ①（看 reason% 占比）+ ②（看 flash / no-think 掉不掉决策质量），再定 lever ②（工作日 RM/PM 降级）值不值。相关：[[watchy-tier2-risk-cadence]] 周日批已砍。

## MOD 单票实测(2026-07-03，新代码上线后第一次；`tests/test_e2e.py MOD`，工作日 risk0)

**已部署**：commits `e27860e`(①TOKENCOST reason + ②compare 脚本) / `97a6081`(④digest + GEMINICOST + ③thinking默认关 + 修parse) / `9dbd740`(README)。手动跑单票 = `sudo -iu watchy; cd ~/watchy; ~/.pyenv/versions/3.11.9/envs/trading/bin/python tests/test_e2e.py <票>`（走完整 watchy 路径，日志打到控制台，grep GEMINICOST/TOKENCOST）。

**单票成本基线 ≈ $0.0355** = DeepSeek **$0.0255** + Gemini advisor **$0.0100**。→ **Gemini 一次调用就占单票 28%**（$9/1M 输出价太贵）。
- **Gemini**：in 4729($0.0071) + out 321($0.0029)，**think=0**（③默认关，确认）。输入是 Gemini 成本大头(71%)。
- **DeepSeek**：out 合计 29,156 token，其中 **thinking 10,280 = 35%**；折算 thinking 成本 ≈ **$0.004 = DeepSeek 的 16%**。flash 16 调用 $0.0192 / pro 2 调用 $0.0063。
- 节点 thinking/out 比：**Research Manager 63%(最高)**、PM 40%、Aggressive 36%、News 33%、Sentiment 31%、Bull/Bear/Fundamentals/Market ~28–29%、Trader 35%。最贵节点：Market $0.0052(输入72k、49k命中缓存)、Fundamentals $0.0035、RM $0.0033、PM $0.0029。

**① digest 省了多少(Gemini)**：现 $0.010/次(实测)；之前喂 4 份全文估 ~$0.020/次(输入~1.1–1.3万token)→ **≈砍一半，−$0.01/次 ≈ 省 $5/月**（估算，老代码无日志；要精确可量 MOD 报告"全文 vs 尾巴"token 差）。

## 降本待办清单（下次接着做，按推荐顺序）

1. **DeepSeek RM/PM pro→flash**（#3，工具就绪）：VPS 上 `export DEEPSEEK_API_KEY=$(python3 -c "import yaml;print(yaml.safe_load(open('/home/watchy/watchy_config/secrets.yaml'))['llm']['deepseek_api_key'])")` 后跑 `scripts/compare_rm_pm_models.py --limit 5`。看 flash vs pro 决策一致性+省多少(pro 本票占 $0.0063)。
2. **🏁 Gemini thinking 已定案(2026-07-03)：Tier 1 = off，Tier 2 = low。**
   - **关键教训**：gemini-3.5-flash 用 **`thinkingConfig.thinkingLevel`**(minimal/low/medium/high，默认 medium)，**3.x 已弃 `thinkingBudget`**。第一次 A/B 我误用 `thinkingBudget:-1`(动态)→ 跑飞 2945 token、截断答案、贵 3.4x → 误判"不开"。用对 `thinkingLevel` 重测(MOD off/low/medium)：off $0.0108(think0)、**low $0.0270(think1906)**、medium $0.0339(think2603)，三档决策都 HOLD/LOW 不变,但 low 推理更细、不截断。
   - **落地**：`LLMConfig.gemini_thinking_tier1="off"` / `gemini_thinking_tier2="low"`(替换旧 `gemini_thinking_budget`)；`advisor._gemini_thinking_config(level)`(off→legacy budget0，其余→thinkingLevel)；`get_advice(...,thinking_level=)`，tier1/tier2 各传自己档位；GEMINICOST 加 `think_level=`。`secrets.yaml` 可覆盖两档。
   - **工具**：`scripts/compare_gemini_thinking.py --ticker X --levels off,low,medium`(重放 advisor 扫档位，不重跑管线)。
   - **删分析师 summary 尾巴省钱？→ 否决(2026-07-03)**：只省输入 ~$0.002–0.003/次(~$1–1.5/月)，而 Tier2 钱大头是 thinking 不是输入；且尾巴是 advisor 引用的证据,删了掉质量。不值。
3. **DeepSeek quick 节点关 thinking**（#2，省~16%）：要给 vendored TA 的 `DeepSeekChatOpenAI` 加 `extra_body={"thinking":{"type":"disabled"}}` 开关(见上文 thinking 事实)，再 on/off 对比质量。最后做。

其它已知杠杆：Gemini 换 flash-lite（输入按 $1.5 计，换便宜模型直接砍）；verdict 未变跳过 advisor（省头小）。
