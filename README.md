# Watchy

A stock monitoring daemon that sits on top of the [TradingAgents](https://github.com/anthropics/TradingAgents) multi-agent LLM trading framework. Watchy watches your watchlist so you don't have to — cheap technical scans every hour, full-depth analysis once a day, and position-aware advice delivered to Telegram.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Watchy Daemon                    │
│                                                   │
│  Tier 1 (hourly)          Tier 2 (daily)          │
│  ─────────────            ─────────────           │
│  OHLCV + indicators       Full 4-analyst          │
│  No LLM calls             pipeline                │
│       │                   + debate                │
│       │                   + risk mgmt             │
│       ▼                        │                  │
│  Signal breach?                │                  │
│       │                        │                  │
│    ┌──┴──┐                     │                  │
│    │ Yes │───→ Graduated ──────┘                  │
│    │     │    analyst subset                      │
│    │ No  │───→ Update state,                      │
│    └─────┘    exit (no cost)                      │
│                                                   │
│  After every pipeline run:                        │
│    Schwab position → LLM advisor → Telegram       │
└─────────────────────────────────────────────────┘
```

**Tier 1** runs per-ticker on configurable intervals (default: hourly). Fetches OHLCV + technical indicators via yfinance — no LLM calls. Detects 11 signal types including golden/death cross (with full MA staircase confirmation), RSI extremes, MACD crossovers, Bollinger breaches, volume anomalies, and ATR spikes. When a signal fires, launches a graduated subset of TradingAgents analysts based on signal significance.

**Tier 2** runs once daily at configured UTC times. Launches the full 4-analyst TradingAgents pipeline (Market, Sentiment, News, Fundamentals) with Bull/Bear debate and 3-way risk management for every ticker on the watchlist.

**After every analysis**, Watchy fetches your Schwab position for the ticker, calls a lightweight LLM (Gemini by default) to synthesize the report + your holdings into actionable advice, and pushes a natural-language summary to Telegram.

## Quick Start

```bash
# 1. Clone into your TradingAgents directory
cd ~/TradingAgents
git clone https://github.com/SConv11/watchy.git

# 2. Install dependencies
pip install -r watchy/requirements.txt
pip install apscheduler  # if not already installed

# 3. Create config
mkdir -p ~/watchy
cp watchy/config.yaml ~/watchy/config.yaml
nano ~/watchy/config.yaml  # fill in watchlist, API keys, Telegram creds

# 4. Run
python -m watchy.daemon
```

### systemd (production)

```bash
sudo cp watchy/watchy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now watchy
journalctl -u watchy -f
```

## Configuration

See `config.yaml` for the full annotated example. Key sections:

| Section | Purpose |
|---------|---------|
| `watchlist` | Tickers to monitor, per-ticker Tier 1 interval and Tier 2 UTC time |
| `signal_thresholds` | RSI, volume, and ATR thresholds for signal detection |
| `cooldown` | Per-signal cooldown windows (prevents spam) |
| `llm` | Advisor LLM config — Gemini, DeepSeek, OpenAI, or Anthropic |
| `telegram` | Bot token and chat ID for notifications |
| `schwab` | Schwab brokerage credentials (optional — enables position-aware advice) |

## Signals Detected

| Signal | Detection | Default Cooldown |
|--------|-----------|------------------|
| Golden Cross | 50MA crosses above 200MA + full staircase (price > 50 > 150 > 200) + 200MA trending up | 7 days |
| Death Cross | 50MA crosses below 200MA | 7 days |
| RSI Oversold | RSI drops below 30 | 12 hours |
| RSI Overbought | RSI rises above 70 | 12 hours |
| MACD Bullish Cross | MACD line crosses above signal line | 24 hours |
| MACD Bearish Cross | MACD line crosses below signal line | 24 hours |
| Bollinger Upper Breach | Price ≥ upper band (2σ) | 6 hours |
| Bollinger Lower Breach | Price ≤ lower band (2σ) | 6 hours |
| Volume Anomaly (≥2x) | Volume ≥ 2× 20-day average | 4 hours |
| Volume Anomaly (≥1.5x) | Volume ≥ 1.5× 20-day average (info only) | 4 hours |
| ATR Spike | ATR ≥ 1.5× 20-day average ATR | 6 hours |

## Graduated Analyst Response

Not all signals need the full 4-analyst pipeline with debate. Watchy scales analysis depth to signal significance:

| Trigger | Analysts | Debate | Risk Mgmt |
|---------|----------|--------|-----------|
| Tier 2 daily | Market + Sentiment + News + Fundamentals | Bull/Bear | Full 3-way |
| Golden/Death Cross | Market + Sentiment + News | Bull/Bear | Full 3-way |
| RSI, MACD, Bollinger, Volume Strong, ATR | Market + Sentiment | Bull/Bear | Simplified |
| Volume Moderate (≥1.5x) | Market only | None | None |

## Telegram Messages

**Signal fired:**
```
Signal Fired — $NVDA
Signal: Golden Cross (50MA ↑ 200MA)
Price: $142.37  RSI: 58.3  SEPA Stage: Advancing
Analysts launching: market, sentiment, news
```

**Analysis complete with position advice (Schwab enabled):**
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

## File Structure

```
watchy/
├── config.yaml              # user-editable configuration
├── requirements.txt         # Python dependencies
├── watchy.service           # systemd unit file
├── project_doc.md           # full technical documentation
└── watchy/                  # package
    ├── __init__.py           # package marker
    ├── config.py             # YAML config → typed dataclasses
    ├── state.py              # SQLite store (crossover memory, cooldown, history)
    ├── indicators.py         # technical indicators (yfinance + pandas, no LLM)
    ├── orchestrator.py       # graduated pipeline selection per signal type
    ├── advisor.py            # LLM synthesis: analysis + position → advice
    ├── schwab.py             # Schwab brokerage API client (stub)
    ├── notify.py             # Telegram Bot notifications
    ├── tier1.py              # hourly signal scanner
    ├── tier2.py              # daily full pipeline
    └── daemon.py             # APScheduler entry point
```

## Wiring TradingAgents

The `pipeline_runner` parameter in `orchestrator.py` is the integration point. Pass a callable `(ticker, PipelineSpec) -> dict` that invokes TradingAgents with the appropriate analyst subset. A stub is provided that logs what would run.

## Documentation

Full technical docs in [`project_doc.md`](project_doc.md) — covers module internals, data flow, deployment, testing strategy, and configuration reference.

## License

MIT
