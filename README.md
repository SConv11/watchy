# Watchy（看门狗）

> 🌐 English version: [README.en.md](README.en.md)


基于 [TradingAgents](https://github.com/anthropics/TradingAgents) 多智能体 LLM 交易框架的股票监控守护进程（daemon）。Watchy 帮你盯着自选股（watchlist）——每小时跑一次零成本的 технический指标扫描（indicator scan），每天跑一次全深度分析（full-depth analysis），并通过 Telegram 推送持仓感知的交易建议（position-aware advice）。

## 架构（Architecture）

```
┌─────────────────────────────────────────────────┐
│                  Watchy 守护进程                   │
│                                                   │
│  第一层 Tier 1（每小时）      第二层 Tier 2（每天）   │
│  ──────────────────────      ──────────────────  │
│  OHLCV + 技术指标             完整四分析师流水线      │
│  不调用 LLM                   (pipeline)           │
│       │                       + 辩论 (debate)      │
│       │                       + 风险管理 (risk)    │
│       ▼                            │              │
│  触发信号？                        │              │
│  (signal breach?)                 │              │
│       │                            │              │
│    ┌──┴──┐                         │              │
│    │ 是  │───→ 分级分析 ────────────┘              │
│    │     │    (graduated subset)                  │
│    │ 否  │───→ 更新状态,                           │
│    └─────┘    退出（零成本）                        │
│                                                   │
│  每次分析完成后：                                   │
│    持仓数据源 → LLM 顾问 → Telegram 推送           │
└─────────────────────────────────────────────────┘
```

**Tier 1（第一层）**按可配间隔（默认每小时）逐票扫描，**仅在美股常规交易时段运行**（休市、周末、节假日自动跳过——靠 `exchange_calendars` 判断，含夏令时/DST 修正）。通过 yfinance 获取 OHLCV 数据并计算技术指标（technical indicators），不调用任何 LLM。检测 11 种信号类型，包括金叉/死叉（golden/death cross，含完整均线阶梯确认 full MA staircase）、RSI 极值、MACD 交叉、布林带突破（Bollinger breach）、成交量异动（volume anomaly）和 ATR 飙升。信号触发时，根据信号重要程度启动分级（graduated）的 TradingAgents 分析师子集。

**Tier 2（第二层）**在配置的 UTC 时间运行（**周一–五 + 周日**，周六跳过，因与周日运行冗余）。对自选股中的每一只票启动完整的四分析师流水线（市场 Market + 情绪 Sentiment + 新闻 News + 基本面 Fundamentals）+ 多空辩论（Bull/Bear debate），风险管理深度按日：**工作日为简化（simplified），周日升级为完整三维风险辩论（3-way risk debate）**。

**Tier 2 价格邻近门控（price-proximity gate，#15，按票可选）**：给某只票设置 `tier2_min_price_proximity_pct` 后，**工作日**若现价离 **入场目标价（entry target）** 超过该百分比，就跳过这次昂贵的 LLM 流水线（省 DeepSeek 成本）。门控只针对 **watch-only（非持仓）** 的票：**只要当前持有该票（position source 查到非零持仓），Tier 2 永远运行**——有资金敞口就值得每天分析，与价格无关（持仓查询出错时也按"持有"处理，宁可多跑）。**周日永远运行**（每周一次完整更新，含新闻）。入场目标价优先用手动 `target_price`，否则用 **自动推导值（#16）**：每次 Tier 2 运行时从顾问输出的结构化 `Target:` 字段提取（语义明确为"建仓/加仓的入场价"，不是止损也不是止盈）并存入 `state.db`（手动值始终优先）。注意 **Tier 1 永不门控**——它是每 30 分钟的常开雷达，远离目标的票之间靠 Tier 1 信号兜底。

**每次分析完成后**，Watchy 获取该票的当前持仓（position），调用轻量 LLM（默认 Gemini）将分析报告与持仓合成可执行的交易建议，推送自然语言摘要到 Telegram。

**持仓数据源（position source，#4）是分层的，保证 Schwab 无法刷新时仍可用**：

1. **Schwab API（实时）** —— 主数据源。每次成功获取后，快照（snapshot）会缓存到 `~/watchy_config/positions_cache.json`。
2. **缓存快照（cached snapshot）** —— 当实时获取失败（token 过期需 7 天重新授权、API 故障、网络中断）时，回退到上次成功的快照，并在推送中标注数据时效（如 `Schwab cache, ... (3d 4h old)`），绝不把陈旧数据当成实时。
3. **手动文件（manual file）** —— 最终兜底：`~/watchy_config/positions.yaml`（schema 见 `positions.example.yaml`）。用于 Schwab 首次授权前的引导，或彻底无可用数据时。手动文件的持仓会用 yfinance 实时价格补全市值与浮动盈亏（unrealized P&L），**同样标注时效**——优先读文件里可选的 `as_of:` 字段（你声明的持仓截至日期），否则退回文件修改时间（mtime）。

> Schwab 实时层通过 **`schwabdev`** 包实现（只读：持仓 + 余额）。首次需在运行守护进程的机器上做一次浏览器 OAuth（schwabdev 打印授权 URL，授权后把回调 URL 粘回终端），token 存到 `tokens_path`（默认 `~/watchy_config/schwab_tokens.json`）；refresh token 有效期 7 天，到期需重新授权——任何实时获取失败都会自动回退到缓存快照、再到手动文件，守护进程不中断。配置见 `secrets.example.yaml` 的 `schwab:` 段。

## 快速开始（Quick Start）

```bash
# 1. 克隆仓库
cd ~
git clone https://github.com/SConv11/watchy.git

# 2. 安装依赖
~/.pyenv/versions/3.11.9/envs/trading/bin/pip install -e ~/watchy
# -e 表示可编辑安装（editable install），后续 git pull 自动生效

# 3. 创建配置文件
mkdir -p ~/watchy_config
cp ~/watchy/config.yaml ~/watchy_config/config.yaml
cp ~/watchy/secrets.example.yaml ~/watchy_config/secrets.yaml

# 4. 填入敏感信息（API key、Telegram token）
nano ~/watchy_config/secrets.yaml

# 5. 编辑自选股（可通过 GitHub 远程编辑，git pull 同步）
nano ~/watchy_config/config.yaml

# 6. 启动（测试用）
WATCHY_CONFIG=~/watchy_config/config.yaml python -m watchy.daemon
```

### systemd 生产部署（Production）

```bash
sudo cp ~/watchy/watchy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now watchy
journalctl -u watchy -f  # 查看日志
```

## 配置（Configuration）

配置分两个文件：

- **`config.yaml`**（可安全提交）—— 自选股、阈值、冷却时间
- **`secrets.yaml`**（git-ignored）—— LLM API key、Telegram token、Schwab 凭证

详见 `config.yaml` 和 `secrets.example.yaml` 中的完整注释。主要配置项：

| 配置项 | 用途 |
|--------|------|
| `watchlist` | 监控的股票列表（自选股），可按票设置 Tier 1 间隔、Tier 2 UTC 时间，以及可选的价格邻近过滤：`target_price` + `tier1_min_price_proximity_pct`（Tier 1，仅当现价在目标价 N% 以内才扫该票）和 `tier2_min_price_proximity_pct`（Tier 2 工作日门控，#15；目标价缺省时用 #16 自动推导值，周日不门控） |
| `signal_thresholds` | RSI、成交量、ATR 等信号检测阈值（thresholds） |
| `cooldown` | 每种信号的冷却窗口（cooldown window），防止重复推送 |
| `tier2_throttle_s` | Tier 2 每日扫描时票与票之间的间隔秒数（默认 2.0），平滑 yfinance 请求、避免触发限流 |
| `llm` | 顾问 LLM 配置——支持 Gemini、DeepSeek、OpenAI、Anthropic |
| `telegram` | Telegram 机器人令牌（bot token）和聊天 ID |
| `schwab` | Schwab 券商凭证（持仓数据主源；未配置时自动回退到缓存/手动文件） |
| `positions.yaml` | 手动持仓文件（最终兜底，放 `~/watchy_config/`，不提交）；schema 见 `positions.example.yaml`。**建议填 `total_account_value:`**（账户总值 = 股票 + 现金 + 现金等价物，直接从券商读到的那个数，作为权威分母；或退而填 `cash:` 让 Watchy 自己加）——让顾问按 **总账户价值** 而非仅股票市值判断集中度，避免把正常持仓误判为「过度集中」而错误建议 TRIM |

> **数据获取与缓存**：行情通过 `yfinance` 获取，并叠加 `yfinance-cache` 磁盘缓存层
> （智能缓存，仅拉取缺失/过期的 bar），减少对 Yahoo 的重复请求。缓存层为可选依赖——
> 未安装时自动退回纯 `yfinance`；缓存出现非限流错误时也会优雅降级，不影响扫描。

## 信号检测（Signals Detected）

| 信号 | 检测逻辑 | 默认冷却 |
|------|----------|----------|
| 金叉 Golden Cross | 50MA 上穿 200MA + 完整阶梯 (price > 50 > 150 > 200) + 200MA 上行 | 7 天 |
| 死叉 Death Cross | 50MA 下穿 200MA | 7 天 |
| RSI 超卖 Oversold | RSI 跌破 30 | 12 小时 |
| RSI 超买 Overbought | RSI 升破 70 | 12 小时 |
| MACD 金叉 Bullish Cross | MACD 线上穿信号线（signal line） | 24 小时 |
| MACD 死叉 Bearish Cross | MACD 线下穿信号线 | 24 小时 |
| 布林上轨突破 Upper Breach | 价格 ≥ 上轨 (2σ) | 6 小时 |
| 布林下轨突破 Lower Breach | 价格 ≤ 下轨 (2σ) | 6 小时 |
| 成交量异动 Volume Anomaly (≥2x) | 成交量 ≥ 20日均量的 2 倍 | 4 小时 |
| 温和放量 Moderate Volume (≥1.5x) | 成交量 ≥ 20日均量的 1.5 倍（仅通知，不启动分析） | 4 小时 |
| ATR 飙升 ATR Spike | ATR ≥ 20日均 ATR 的 1.5 倍 | 6 小时 |

> **触发语义**：交叉类（金叉/死叉、MACD、RSI）和水平类（布林、成交量、ATR）信号都是
> **进入态触发（fire on entry）**——只在「从未满足到满足」的那一刻触发一次，条件持续
> 存在期间保持静默，待条件解除并再次穿越才会重新触发。冷却时间是触发之上的额外去重窗口。

## 分级分析师响应（Graduated Analyst Response）

并非所有信号都需要完整的四分析师辩论。Watchy 根据信号重要程度分级调用：

| 触发条件 Trigger | 分析师 Analysts | 辩论 Debate | 风险管理 Risk |
|------------------|----------------|-------------|---------------|
| Tier 2 每日运行（周一–五） | 市场 + 情绪 + 新闻 + 基本面 | 多空 Bull/Bear | 简化 Simplified |
| Tier 2 周日运行 | 市场 + 情绪 + 新闻 + 基本面 | 多空 Bull/Bear | 完整三维 Full 3-way |
| Tier 2 周六 | —（跳过，与周日运行冗余） | — | — |
| 金叉/死叉 | 市场 + 情绪 + 新闻 | 多空 | 完整三维 |
| RSI、MACD、布林、强放量、ATR | 市场 + 情绪 | 多空 | 简化 Simplified |
| 温和放量 (≥1.5x) | 仅市场 Market only | 无 None | 无 None |

## Telegram 消息示例

**信号触发时：**
```
Signal Fired — $NVDA
Signal: Golden Cross (50MA ↑ 200MA)
Price: $142.37  RSI: 58.3  SEPA Stage: Advancing
Analysts launching: market, sentiment, news
```

**分析完成 + 持仓建议（Schwab 启用后）：**
```
Analysis Complete — $NVDA
Trigger: Golden Cross (50MA ↑ 200MA)
Verdict: 🟢 BUY (4 analysts)

📋 Trader Plan
Action: Buy. Disciplined accumulation on pullbacks; AWS/AI thesis
intact, near-term momentum mixed. (shown in full)

⚖️ Risk / Final Call
Rating: Overweight. Initiate half-size at ~$246, hard stop $229.50,
targets $274/$300/$317. (shown in full)
```

> 分析完成的消息只保留两块**已消化**的内容——交易员计划（Trader Plan）与组合经理的
> 最终判定（Risk / Final Call），**完整不截断**（超长由分块发送）。各分析师的原始报告
> 不再塞进消息正文，而是作为完整的 `.md` 报告附件发送。持仓 + 顾问建议在**另一条**消息里：

```
Your Position:
Current position in NVDA:
  Shares: 50  Average cost: $98.40
  Market value: $7,118.50  Unrealized P&L: $2,198.50

Position Advice: 🟢 ADD (low urgency)
You hold 50 shares with 44% gain. The golden cross confirms the
uptrend is intact. Analysts are bullish with targets 15% above current.
Suggested size: 10-15 shares (~2% of portfolio)
Key risk: If price breaks below the 50MA, the signal is invalidated.
```

## 文件结构（File Structure）

```
watchy/
├── config.yaml              # 非敏感配置（可安全提交，通过 GitHub 编辑）
├── secrets.example.yaml     # 敏感配置模板（本地拷贝后填入真实 key）
├── requirements.txt         # Python 依赖
├── watchy.service           # systemd 单元文件
├── project_doc.md           # 完整技术文档（英文）
└── watchy/                  # 包
    ├── __init__.py           # 包标记
    ├── config.py             # YAML 配置 → 类型化数据类 (dataclass)
    ├── state.py              # SQLite 状态存储 (交叉记忆、冷却、历史)
    ├── indicators.py         # 技术指标计算 (yfinance + pandas, 无 LLM)
    ├── orchestrator.py       # 按信号类型的分级流水线选择
    ├── advisor.py            # LLM 合成: 分析报告 + 持仓 → 交易建议
    ├── positions.py          # 分层持仓源: Schwab → 缓存快照 → 手动文件
    ├── schwab.py             # Schwab 券商 API 客户端 (实时层, schwabdev)
    ├── notify.py             # Telegram 机器人通知
    ├── tier1.py              # 每小时信号扫描
    ├── tier2.py              # 每日完整流水线
    └── daemon.py             # APScheduler 入口
```

## 对接 TradingAgents（Wiring）

`orchestrator.py` 中的 `pipeline_runner` 参数是对接点。传入一个可调用对象 `(ticker, PipelineSpec) -> dict`，在其中调用 TradingAgents 的相应分析师子集。当前提供桩实现（stub），仅记录日志不实际调用。

## 文档（Documentation）

完整技术文档见 [`project_doc.md`](project_doc.md) —— 涵盖模块内部实现、数据流、部署、测试策略和配置参考。

## 许可证（License）

MIT
