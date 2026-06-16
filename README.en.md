# Watchy

> 🌐 中文版: [README.md](README.md)

A stock-monitoring daemon built on the [TradingAgents](https://github.com/anthropics/TradingAgents)
multi-agent LLM trading framework. Watchy watches your watchlist for you — an
hourly zero-cost technical indicator scan, a daily full-depth analysis, and
position-aware advice pushed to Telegram.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Watchy daemon                    │
│                                                   │
│  Tier 1 (hourly)            Tier 2 (daily)        │
│  ──────────────────────     ──────────────────    │
│  OHLCV + indicators         full 4-analyst        │
│  no LLM                     pipeline              │
│       │                     + debate              │
│       │                     + risk management     │
│       ▼                          │                │
│  signal breach?                  │                │
│       │                          │                │
│    ┌──┴──┐                       │                │
│    │ yes │───→ graduated ────────┘                │
│    │     │     subset                             │
│    │ no  │───→ update state,                      │
│    └─────┘     exit (zero cost)                   │
│                                                   │
│  after every analysis:                            │
│    position source → LLM advisor → Telegram       │
└─────────────────────────────────────────────────┘
```

**Tier 1** scans each ticker at a configurable interval (hourly by default) and
**runs only during US regular trading hours** — market closures, weekends, and
holidays are skipped automatically via `exchange_calendars` (DST-correct). It
fetches OHLCV through yfinance and computes technical indicators with no LLM
calls. It detects 11 signal types: golden/death cross (with the full moving-
average staircase confirmation), RSI extremes, MACD crossovers, Bollinger band
breaches, volume anomalies, and ATR spikes. When a signal fires, it launches a
graduated subset of TradingAgents analysts sized to the signal's significance.

**Tier 2** runs at a configured UTC time (**Mon–Fri + Sun**; Saturday is skipped
as redundant with Sunday). For every watchlist ticker it launches the full
four-analyst pipeline (Market + Sentiment + News + Fundamentals) with a Bull/Bear
debate. Risk-management depth is day-of-week dependent: **simplified on weekdays,
escalated to the full 3-way risk debate on Sundays.**

**Tier 2 price-proximity gate (#15):** set a **global default** percent via the
top-level `min_price_proximity_pct` (applied to every watch-only ticker; a
per-ticker `min_price_proximity_pct` overrides it). **On weekdays**, the expensive
LLM pipeline is skipped when the current price is farther than that percent from
the **entry target** (saving DeepSeek cost). The gate is **watch-only**: **a
ticker you currently hold (the position source reports a non-zero position) is
always analysed**, regardless of price — capital at risk is worth the daily
tokens (a position-lookup error is treated as "held" too, erring toward running).
**Sunday always runs** (a weekly full update incl. news). The entry target uses a
manual `target_price` first, otherwise an **auto-derived value (#16)**: each Tier
2 run extracts it from the advisor's structured `Target:` field — semantically an
**entry / accumulation level only** (not a stop-loss, not a take-profit) — and
stores it in `state.db` (a manual value always wins). Note **Tier 1 is never
gated** — it's the always-on 30-minute radar that covers far-from-target names
between gated Tier 2 runs.

**ATR-adaptive band (#15 follow-up, optional):** instead of a fixed percent, set
`atr_proximity_mult` (global, or per-ticker) to make the band `mult × ATR%`
(ATR% = `avg_atr_20d / price × 100`) — i.e. *skip when price is more than `mult`
typical trading days of movement from target*. Volatile names get a wider band,
calm names a narrower one. The band is clamped to `[proximity_pct_floor,
proximity_pct_ceiling]` (default 4–20%) and falls back to the fixed percent when
ATR data is unavailable. Calibrate the multiple against your watchlist with
`scripts/calibrate_atr_proximity.py` before enabling.

**Tier 2 batch order (#21):** the daily batch runs **held tickers first** (capital
at risk), then watch-only **nearest-to-target first**, then no-target names last —
so if a long batch is interrupted (auto-update restart, crash, token expiry), the
most important names were analysed first. Indicators are pre-fetched once per
ticker (throttled) and reused by the pipeline (no double fetch).

**After every analysis**, Watchy fetches the ticker's current position, calls a
lightweight LLM (Gemini by default) to synthesize the analysis report + position
into actionable advice, and pushes a natural-language summary to Telegram.

**The position source (#4) is layered, so it keeps working when Schwab can't
refresh:**

1. **Schwab API (live)** — the primary source. Each successful fetch is snapshotted
   to `~/watchy_config/positions_cache.json`.
2. **Cached snapshot** — when a live fetch fails (a token needing 7-day re-auth, an
   API error, a network outage), it falls back to the last good snapshot and labels
   the data's age in the push (e.g. `Schwab cache, ... (3d 4h old)`), never passing
   stale data off as live.
3. **Manual file** — the final fallback: `~/watchy_config/positions.yaml` (schema in
   `positions.example.yaml`). For bootstrapping before Schwab's first auth, or when
   no other data is available. Manual holdings are enriched with live yfinance prices
   for market value and unrealized P&L, **also age-labelled** — preferring the file's
   optional `as_of:` field (the date you state your holdings are current as of),
   otherwise the file's mtime.

> The Schwab live layer uses **`schwabdev`** (read-only: positions + balances). The
> first run needs a one-time browser OAuth on the host machine (schwabdev prints an
> authorization URL; paste the callback URL back into the terminal); tokens are stored
> at `tokens_path` (a schwabdev 3.x SQLite db, default `~/watchy_config/schwab_tokens.db`). The refresh token
> lasts 7 days; on expiry, re-auth — any live-fetch failure falls back to the cache
> then the manual file, so the daemon never stops. See the `schwab:` section of
> `secrets.example.yaml`.
>
> **Positions are fetched once per Tier 2 batch and shared across all tickers** (one
> consistent holdings view + one API call, instead of one call per ticker). Tier 1
> fetches on a fired signal, before running the pipeline.
>
> **Token-expiry alerts (no more silent staleness):** each Tier 2 batch (and each
> Tier 1 fired-signal scan) inspects the position snapshot it just resolved and pushes
> a Telegram alert when the refresh token has **already lapsed** (re-auth needed — the
> scan is on cached/manual data) or is **expiring soon** (within ~1 day of the 7-day
> limit). No extra API call — it reads the fetch the scan already did. Alerts are
> deduped to at most one re-auth nag per day. The 7-day clock is stamped by
> `scripts/schwab_oauth.py` on a successful auth, so re-auth via that script keeps the
> warnings accurate.

## Quick Start

```bash
# 1. Clone
cd ~
git clone https://github.com/SConv11/watchy.git

# 2. Install (editable, so git pull takes effect without reinstalling)
~/.pyenv/versions/3.11.9/envs/trading/bin/pip install -e ~/watchy

# 3. Create config files
mkdir -p ~/watchy_config
cp ~/watchy/config.yaml ~/watchy_config/config.yaml
cp ~/watchy/secrets.example.yaml ~/watchy_config/secrets.yaml

# 4. Fill in secrets (API keys, Telegram token)
nano ~/watchy_config/secrets.yaml

# 5. Edit the watchlist (can be done remotely on GitHub, synced via git pull)
nano ~/watchy_config/config.yaml

# 6. Run (for testing)
WATCHY_CONFIG=~/watchy_config/config.yaml python -m watchy.daemon
```

### Production (systemd)

```bash
sudo cp ~/watchy/watchy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now watchy
journalctl -u watchy -f  # follow logs
```

## Configuration

Config is split across two files:

- **`config.yaml`** (safe to commit) — watchlist, thresholds, cooldowns
- **`secrets.yaml`** (git-ignored) — LLM API keys, Telegram token, Schwab credentials

See the full inline comments in `config.yaml` and `secrets.example.yaml`. Key settings:

| Setting | Purpose |
|---------|---------|
| `watchlist` | Tickers to monitor. Per-ticker overrides: Tier 1 interval, Tier 2 UTC time, optional `target_price`, and a per-ticker `min_price_proximity_pct` override (Tier 2 weekday gate, #15, defaults to the top-level global value; falls back to the #16 auto-derived target, never gated on Sunday or when held). Tier 1 is never proximity-gated — it always scans during market hours. |
| `min_price_proximity_pct` | **Global default** percent for the Tier 2 proximity gate (#15), applied to every watch-only (non-held) ticker; on weekdays skip the daily LLM when price is farther than this from the entry target. Held tickers and Sunday always run; Tier 1 is unaffected. Override per-ticker with the same key. Remove to disable globally. |
| `atr_proximity_mult` | Optional ATR-adaptive band (#15 follow-up), global or per-ticker. When set (and ATR data is available), the gate band is `mult × ATR%` (`ATR% = avg_atr_20d / price × 100`) instead of the fixed percent — wider for volatile names, narrower for calm ones. Clamped to `[proximity_pct_floor, proximity_pct_ceiling]` (default 4–20%); falls back to `min_price_proximity_pct` without ATR data. Calibrate with `scripts/calibrate_atr_proximity.py`. |
| `signal_thresholds` | Detection thresholds for RSI, volume, ATR, etc. |
| `cooldown` | Per-signal cooldown window to suppress repeat pushes |
| `tier2_throttle_s` | Seconds to sleep between tickers in a Tier 2 daily scan (default 2.0), to smooth yfinance requests and avoid rate limits |
| `llm` | Advisor LLM config — supports Gemini, DeepSeek, OpenAI, Anthropic |
| `telegram` | Telegram bot token and chat ID |
| `schwab` | Schwab brokerage credentials (primary position source; auto-falls back to cache/manual file when unconfigured) |
| `positions.yaml` | Manual positions file (final fallback, in `~/watchy_config/`, not committed); schema in `positions.example.yaml`. **Set `total_account_value:`** (the full account figure from your broker — equities + cash + equivalents — used directly as the concentration denominator; or use `cash:` to have Watchy add the buffer to live stock value) so the advisor judges concentration against **Total Account Value**, not the stock-only total, avoiding false "over-concentration" TRIM advice |

> **Data fetching & caching:** market data is fetched via `yfinance` with a
> `yfinance-cache` disk layer on top (smart caching — only the missing/stale bars
> are pulled), cutting redundant Yahoo requests. The cache layer is an optional
> dependency — it falls back to plain `yfinance` when absent, and degrades
> gracefully on non-rate-limit cache errors without disrupting the scan.

## Signals Detected

| Signal | Logic | Default cooldown |
|--------|-------|------------------|
| Golden Cross | 50MA crosses above 200MA + full staircase (price > 50 > 150 > 200) + 200MA rising | 7 days |
| Death Cross | 50MA crosses below 200MA | 7 days |
| RSI Oversold | RSI drops below 30 | 12 hours |
| RSI Overbought | RSI rises above 70 | 12 hours |
| MACD Bullish Cross | MACD line crosses above the signal line | 24 hours |
| MACD Bearish Cross | MACD line crosses below the signal line | 24 hours |
| Bollinger Upper Breach | Price ≥ upper band (2σ) | 6 hours |
| Bollinger Lower Breach | Price ≤ lower band (2σ) | 6 hours |
| Volume Anomaly (≥2x) | Volume ≥ 2× the 20-day average | 4 hours |
| Moderate Volume (≥1.5x) | Volume ≥ 1.5× the 20-day average (notify only, no analysis) | 4 hours |
| ATR Spike | ATR ≥ 1.5× the 20-day average ATR | 6 hours |

> **Trigger semantics:** both crossover signals (golden/death, MACD, RSI) and
> level signals (Bollinger, volume, ATR) **fire on entry** — once, at the moment
> the condition goes from unmet to met. They stay silent while the condition
> persists, and only re-arm once it clears and crosses again. The cooldown is an
> additional dedup window layered on top of the trigger.

## Graduated Analyst Response

Not every signal warrants a full four-analyst debate. Watchy scales the call to
the signal's significance:

| Trigger | Analysts | Debate | Risk |
|---------|----------|--------|------|
| Tier 2 daily (Mon–Fri) | Market + Sentiment + News + Fundamentals | Bull/Bear | Simplified |
| Tier 2 Sunday | Market + Sentiment + News + Fundamentals | Bull/Bear | Full 3-way |
| Tier 2 Saturday | — (skipped, redundant with Sunday) | — | — |
| Golden / Death Cross | Market + Sentiment + News | Bull/Bear | Full 3-way |
| RSI, MACD, Bollinger, strong volume, ATR | Market + Sentiment | Bull/Bear | Simplified |
| Moderate volume (≥1.5x) | Market only | None | None |

## Telegram Message Examples

**On a signal firing:**
```
Signal Fired — $NVDA
Signal: Golden Cross (50MA ↑ 200MA)
Price: $142.37  RSI: 58.3  SEPA Stage: Advancing
Analysts launching: market, sentiment, news
```

**On analysis complete:**
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

> The analysis-complete message keeps only the two **digested** blocks — the
> Trader Plan and the Portfolio Manager's Risk / Final Call — **in full, never
> truncated** (chunked across messages if long). The raw per-analyst reports are
> no longer crammed into the message body; they're sent as the complete `.md`
> report attachment. The position + advisor advice ride in a **separate** message:

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

## File Structure

```
watchy/
├── config.yaml              # non-sensitive config (safe to commit, edit via GitHub)
├── secrets.example.yaml     # sensitive-config template (copy locally, fill in keys)
├── requirements.txt         # Python dependencies
├── watchy.service           # systemd unit file
├── project_doc.md           # full technical documentation
└── watchy/                  # package
    ├── __init__.py           # package marker
    ├── config.py             # YAML config → typed dataclasses
    ├── state.py              # SQLite state store (crossover memory, cooldown, history)
    ├── indicators.py         # technical-indicator computation (yfinance + pandas, no LLM)
    ├── proximity.py          # shared price-proximity gate (Tier 1 & Tier 2)
    ├── orchestrator.py       # graduated pipeline selection per signal type
    ├── advisor.py            # LLM synthesis: analysis report + position → advice
    ├── positions.py          # layered position source: Schwab → cached snapshot → manual file
    ├── schwab.py             # Schwab brokerage API client (live layer, schwabdev)
    ├── notify.py             # Telegram bot notifications
    ├── tier1.py              # hourly signal scan
    ├── tier2.py              # daily full pipeline
    └── daemon.py             # APScheduler entry point
```

## Wiring TradingAgents

The `pipeline_runner` argument in `orchestrator.py` is the integration point. Pass
a callable `(ticker, PipelineSpec) -> dict` that invokes the appropriate
TradingAgents analyst subset. A stub is provided by default (logs only, no real
call); `watchy/pipeline_runner.py` is the real bridge.

## Documentation

See [`project_doc.md`](project_doc.md) for full technical documentation — module
internals, data flow, deployment, testing strategy, and a config reference.

## License

MIT
