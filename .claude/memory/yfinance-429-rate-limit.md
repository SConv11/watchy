---
name: yfinance-429-rate-limit
description: yfinance 429 + 1.x 升级兼容性 — 全部已修已 push
metadata:
  type: project
  node_type: memory
  originSessionId: b1456a24-9c49-4d0a-9ae3-94abfb219ebf
---

## 已解决 (2026-06-03)

### 1. yfinance 1.x 不兼容 requests.Session
yfinance 1.x 用 `curl_cffi` 反爬，不再接受 `requests.Session`。

| 项目 | 状态 |
|------|------|
| TradingAgents | ✅ 6 文件删 session + 加 YFRateLimitError fallback |
| watchy | ✅ `indicators.py` 删 session |

### 2. TradingAgents fallback
`interface.py` 只 catch `AlphaVantageRateLimitError` → 加 `YFRateLimitError`。

### 3. 本地 429
用 Clash 代理 `finance.yahoo.com` 解决。

## 待观察

### VPS 批量 429
16 只票 Tier 2 可能瞬间大量请求。下次 session 评估：
- `tier2.py` 加 `time.sleep(2)` 间隔
- [yfinance-cache](https://github.com/ValueRaider/yfinance-cache) — 磁盘缓存，减少重复请求
