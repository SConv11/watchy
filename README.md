# SSH不要开TUN
---

# Watchy（看门狗）

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
│    Schwab 持仓 → LLM 顾问 → Telegram 推送          │
└─────────────────────────────────────────────────┘
```

**Tier 1（第一层）**按可配间隔（默认每小时）逐票扫描。通过 yfinance 获取 OHLCV 数据并计算技术指标（technical indicators），不调用任何 LLM。检测 11 种信号类型，包括金叉/死叉（golden/death cross，含完整均线阶梯确认 full MA staircase）、RSI 极值、MACD 交叉、布林带突破（Bollinger breach）、成交量异动（volume anomaly）和 ATR 飙升。信号触发时，根据信号重要程度启动分级（graduated）的 TradingAgents 分析师子集。

**Tier 2（第二层）**在配置的 UTC 时间每天运行一次。对自选股中的每一只票启动完整的四分析师流水线（市场 Market + 情绪 Sentiment + 新闻 News + 基本面 Fundamentals），含多空辩论（Bull/Bear debate）和三维风险管理（3-way risk management）。

**每次分析完成后**，Watchy 从 Schwab 获取该票的当前持仓（position），调用轻量 LLM（默认 Gemini）将分析报告与持仓合成可执行的交易建议，推送自然语言摘要到 Telegram。

## 快速开始（Quick Start）

```bash
# 1. 克隆到 TradingAgents 目录下
cd ~/TradingAgents
git clone https://github.com/SConv11/watchy.git

# 2. 安装依赖
pip install -r watchy/requirements.txt
pip install apscheduler  # 如未安装

# 3. 创建配置文件
mkdir -p ~/watchy
cp watchy/config.yaml ~/watchy/config.yaml
nano ~/watchy/config.yaml  # 填写自选股、API 密钥、Telegram 凭证

# 4. 启动
python -m watchy.daemon
```

### systemd 生产部署（Production）

```bash
sudo cp watchy/watchy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now watchy
journalctl -u watchy -f  # 查看日志
```

## 配置（Configuration）

详见 `config.yaml` 中的完整注释示例。主要配置项：

| 配置项 | 用途 |
|--------|------|
| `watchlist` | 监控的股票列表（自选股），可按票设置 Tier 1 间隔和 Tier 2 UTC 时间 |
| `signal_thresholds` | RSI、成交量、ATR 等信号检测阈值（thresholds） |
| `cooldown` | 每种信号的冷却窗口（cooldown window），防止重复推送 |
| `llm` | 顾问 LLM 配置——支持 Gemini、DeepSeek、OpenAI、Anthropic |
| `telegram` | Telegram 机器人令牌（bot token）和聊天 ID |
| `schwab` | Schwab 券商凭证（可选——启用后获得持仓感知建议） |

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

## 分级分析师响应（Graduated Analyst Response）

并非所有信号都需要完整的四分析师辩论。Watchy 根据信号重要程度分级调用：

| 触发条件 Trigger | 分析师 Analysts | 辩论 Debate | 风险管理 Risk |
|------------------|----------------|-------------|---------------|
| Tier 2 每日运行 | 市场 + 情绪 + 新闻 + 基本面 | 多空 Bull/Bear | 完整三维 Full 3-way |
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
Recommendation: moderate bullish, accumulate on pullback
Risk: medium — sector rotation risk

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
├── config.yaml              # 用户可编辑的配置文件
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
    ├── schwab.py             # Schwab 券商 API 客户端 (桩代码 stub)
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
