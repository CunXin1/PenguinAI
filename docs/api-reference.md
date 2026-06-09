# API Reference

## English

Base URL: `http://localhost:8000/api` (local) · `https://your-domain.com/api` (production)

Authentication: `Authorization: Bearer <access_token>` header (JWT)

---

### Authentication

#### `POST /auth/register`
Create a new user account.

**Request**
```json
{
  "email": "user@example.com",
  "password": "minimum8chars",
  "display_name": "Optional Name"
}
```

**Response** `201 Created`
```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

**Errors**: `409 Conflict` (email already exists)

---

#### `POST /auth/login`
Authenticate and receive a JWT token.

**Request**
```json
{ "email": "user@example.com", "password": "yourpassword" }
```

**Response** `200 OK`
```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

**Errors**: `401 Unauthorized` (invalid credentials)

---

#### `GET /auth/me`
Get current authenticated user info.

**Auth**: Required

**Response** `200 OK`
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "display_name": "Name",
  "tier": "FREE",
  "created_at": "2026-05-31T00:00:00Z"
}
```

---

### Signals

#### `GET /signals/top`
Get pre-computed Top-N signals (instant, from cache).

**Auth**: Not required

**Query params**:
| Param | Type | Default | Max |
|-------|------|---------|-----|
| `limit` | int | 100 | 200 |

**Response** `200 OK`
```json
[
  {
    "ticker": "NVDA",
    "direction": "LONG",
    "confidence": 0.82,
    "holding_period": "SHORT_TERM",
    "computed_at": "2026-05-31T14:00:00Z"
  },
  ...
]
```

---

#### `GET /signals/{ticker}`
Get signal for a specific ticker.

**Auth**: Required (tier check applied)

**Path params**: `ticker` — uppercase stock symbol (e.g. `NVDA`, `SPY`)

**Response** `200 OK` (cache hit)
```json
{
  "ticker": "NVDA",
  "direction": "LONG",
  "confidence": 0.82,
  "holding_period": "SHORT_TERM",
  "ml_scores": {
    "xgb_prob_up": 0.75,
    "rf_prob_up": 0.71,
    "ensemble_prob": 0.74
  },
  "sentiment": {
    "finbert_score": 0.68,
    "post_count": 15,
    "hawk_dove_ref": -0.2
  },
  "ai_attribution": "XGBoost 75% upside prob, FinBERT +0.68 on 15 posts, Cathie Wood recent BUY.",
  "ai_analysis": "NVDA shows strong short-term momentum aligned with institutional accumulation...",
  "tier_required": "FREE",
  "computed_at": "2026-05-31T14:00:00Z",
  "expires_at": "2026-05-31T15:00:00Z"
}
```

**Response** `202 Accepted` (cache miss — computation triggered)
```json
{
  "message": "Signal computation triggered",
  "ticker": "NVDA",
  "retry_after": 5
}
```
Poll again after `retry_after` seconds.

**Errors**:
- `401` — Not authenticated
- `403` — Insufficient tier for this signal
- `422` — Invalid ticker format

---

### Tickers

#### `GET /tickers/search`
Search tickers by symbol or name.

**Query params**:
| Param | Type | Required |
|-------|------|---------|
| `q` | string (1–20 chars) | Yes |

**Response** `200 OK`
```json
[
  { "ticker": "NVDA", "name": "NVIDIA Corp.", "sector": "Technology", "exchange": "NASDAQ" },
  { "ticker": "NVDQ", "name": "NVIDIA Leveraged...", "sector": "ETF", "exchange": "NYSE" }
]
```

---

#### `GET /tickers/universe`
List the full stock universe with pagination.

**Query params**:
| Param | Type | Default |
|-------|------|---------|
| `offset` | int | 0 |
| `limit` | int (max 500) | 100 |
| `sector` | string | — |
| `tag` | string | — |

---

#### `GET /tickers/{ticker}`
Get metadata for a specific ticker.

**Response** `200 OK`
```json
{
  "ticker": "NVDA",
  "name": "NVIDIA Corp.",
  "exchange": "NASDAQ",
  "sector": "Technology",
  "industry": "Semiconductors",
  "market_cap": 3200000000000,
  "tags": ["tech", "sp500", "ai", "semiconductor"],
  "is_active": true
}
```

---

### Watchlist

#### `GET /watchlist`
Get current user's watchlist with latest signals.

**Auth**: Required

**Response** `200 OK`
```json
[
  {
    "ticker": "NVDA",
    "signal": {
      "ticker": "NVDA",
      "direction": "LONG",
      "confidence": 0.82,
      "holding_period": "SHORT_TERM",
      "computed_at": "..."
    }
  },
  { "ticker": "AAPL", "signal": null }
]
```

---

#### `POST /watchlist/{ticker}`
Add a ticker to watchlist.

**Auth**: Required

**Response** `201 Created`
```json
{ "ticker": "NVDA", "added": true }
```

**Errors**: `404` (ticker not in universe), `409` (already in watchlist)

---

#### `DELETE /watchlist/{ticker}`
Remove a ticker from watchlist.

**Auth**: Required

**Response** `204 No Content`

---

### Market Data

#### `GET /market-data/{ticker}/candles`
Get raw OHLCV bars for charting (legacy/simple form).

**Query params**:
| Param | Type | Default | Options |
|-------|------|---------|---------|
| `timeframe` | string | `30min` | `1min`, `30min`, `1day` |
| `days` | int | 30 | 1–365 |

**Response** `200 OK`
```json
{
  "ticker": "NVDA",
  "timeframe": "30min",
  "candles": [
    { "time": "2026-05-30T09:30:00Z", "open": 900.0, "high": 915.0, "low": 898.0, "close": 910.0, "volume": 5200000 }
  ]
}
```

---

#### `GET /market-data/{ticker}/series`
Range-bucketed OHLC series for the frontend `PriceChart`. Tries the live minute
store (`market_data_1min` / daily cagg) first, then falls back to imported
30-min/daily bars so every symbol in the ~6,300 universe charts on all ranges.

**Query params**:
| Param | Type | Default | Options |
|-------|------|---------|---------|
| `range` | string | `1W` | `1D`, `1W`, `1M`, `3M`, `1Y` |

**Response** `200 OK`
```json
{
  "ticker": "NVDA",
  "range": "1W",
  "bars": [
    { "time": 1748599200, "open": 900.0, "high": 915.0, "low": 898.0, "close": 910.0, "volume": 5200000 }
  ]
}
```
`time` is unix seconds (TradingView `UTCTimestamp`).

---

#### `GET /market-data/quotes`
Batch latest-quote board: newest 1-min close + same-session % change per ticker.
Powers the homepage live board. Reads `market_data_1min` (IBKR stream).

**Query params**: `tickers` — comma-separated, e.g. `QQQ,SPY,NVDA` (max 60)

**Response** `200 OK`
```json
{ "quotes": [ { "ticker": "NVDA", "price": 910.12, "change_pct": 1.34, "time": "2026-05-30T15:59:00Z" } ] }
```

---

#### `GET /market-data/mini`
Index-strip data: latest price + same-session % change + a downsampled intraday
spark per ticker, batched in one round-trip. Powers the homepage market-overview
strip.

**Query params**: `tickers` — comma-separated (max 12)

**Response** `200 OK`
```json
{ "items": [ { "ticker": "QQQ", "price": 480.1, "change_pct": 0.62, "time": "...", "spark": [479.2, 479.8, 480.1] } ] }
```

---

#### `GET /market-data/heatmap`
Market-cap heatmap tiles — sized by `tickers.market_cap`, colored by % change.
Market closed → last daily close + prior-session move; market open → live price
from `market_data_1min` vs prior close.

**Query params**:
| Param | Type | Default | Max |
|-------|------|---------|-----|
| `limit` | int | 100 | 500 |

**Response** `200 OK`
```json
{
  "market_open": false,
  "as_of": "2026-05-30T21:00:00Z",
  "count": 100,
  "items": [
    { "ticker": "NVDA", "name": "NVIDIA Corp.", "sector": "Technology", "market_cap": 3200000000000, "price": 910.0, "change_pct": 1.34 }
  ]
}
```

---

### Earnings

#### `GET /earnings/calendar`
Earnings calendar for a date window.

**Query params**:
| Param | Type | Default |
|-------|------|---------|
| `from` | date | today − 7d |
| `to` | date | today + 30d |

**Response** `200 OK`
```json
[
  {
    "ticker": "NVDA",
    "report_date": "2026-05-28",
    "eps_actual": 1.21,
    "eps_estimate": 1.10,
    "eps_surprise_pct": 10.0,
    "revenue_actual": 44000000000,
    "revenue_estimate": 42000000000,
    "guidance_text": null,
    "name": "NVIDIA Corp.",
    "session": "AMC"
  }
]
```
`session` ∈ `BMO` (pre-open) · `AMC` (after-close) · `TBD`.

**Errors**: `422` (`to` before `from`)

---

#### `GET /earnings/{ticker}`
Most recent earnings history for one ticker (newest first).

**Query params**: `limit` — int, default 12, max 40

**Response** `200 OK` — same `EarningsEvent` array shape as `/calendar`.

---

### Celebrity Holdings

#### `GET /celebrity-holdings`
Recent transactions across all tracked celebrities.

**Query params**:
| Param | Type | Default | Max |
|-------|------|---------|-----|
| `limit` | int | 100 | 500 |
| `offset` | int | 0 | — |

**Response** `200 OK`
```json
[
  {
    "id": "uuid",
    "reported_at": "2026-05-15T00:00:00+00:00",
    "celebrity": "buffett",
    "ticker": "AAPL",
    "ticker_name": "Apple Inc.",
    "action": "HOLD",
    "shares": 400000000,
    "value_usd": 85720000000,
    "source_type": "13F",
    "filing_url": "https://www.sec.gov/..."
  }
]
```

---

#### `GET /celebrity-holdings/stats/summary`
Per-celebrity aggregate stats.

**Response** `200 OK`
```json
[
  {
    "celebrity": "buffett",
    "total_trades": 24,
    "buys": 8,
    "sells": 4,
    "latest_trade": "2026-05-15T00:00:00+00:00"
  }
]
```

---

#### `GET /celebrity-holdings/{celebrity}`
All trades for one celebrity.

**Path params**: `celebrity` — lowercase slug (`buffett`, `pelosi`, `cathie_wood`, `trump`, etc.)

**Query params**: `limit` — int, default 100, max 500

**Response** `200 OK` — same array shape as `/celebrity-holdings`.

**Errors**: `422` (invalid celebrity slug format)

---

#### `GET /celebrity-holdings/ticker/{ticker}`
Which celebrities traded a given ticker.

**Path params**: `ticker` — uppercase symbol

**Query params**: `limit` — int, default 50, max 200

**Response** `200 OK` — same array shape as `/celebrity-holdings`.

**Errors**: `422` (invalid ticker format)

---

### Symbols

#### `POST /symbols/request`
Record demand for a symbol not in our universe. Deduped by symbol — repeat
requests bump `request_count`; a background job
(`ml.tasks.symbol_validation`) later classifies it against Massive. No free text
reaches any LLM.

**Request**
```json
{ "symbol": "ABCD" }
```

**Response** `200 OK`
```json
{ "symbol": "ABCD", "status": "pending", "request_count": 1, "message": "Thanks — we logged your request for ABCD..." }
```
`status` ∈ `pending` · `already_covered` · `real_pending_ingest` · `delisted` · `rejected_junk` · `ingested`.

**Errors**: `422` (invalid symbol format)

---

#### `GET /symbols/requests`
Admin: inspect the data-demand queue, most-requested first.

**Auth**: ADMIN tier

**Query params**: `status` (filter), `limit` (default 100, max 500)

---

### Admin (ADMIN tier only)

#### `GET /admin/pipeline/status`
Get data pipeline health metrics.

**Response** `200 OK`
```json
{
  "db_stats": {
    "bars_30min": 236000000,
    "bars_1min": 27000000,
    "social_posts": 0,
    "cached_signals": 98
  }
}
```

---

#### `POST /admin/cache/refresh`
Manually trigger Top-100 signal cache refresh.

**Response** `200 OK`
```json
{ "triggered": true }
```

---

## 中文

### 接口规范

- **基础 URL**：`http://localhost:8000/api`（本地开发）
- **认证方式**：`Authorization: Bearer <access_token>` 请求头（JWT）
- **Token 有效期**：7 天

### 信号接口说明

`GET /signals/{ticker}` 有两种响应：
- `200 OK`：缓存命中，直接返回完整信号 JSON（< 10ms）
- `202 Accepted`：缓存未命中，触发后台计算，返回 `retry_after: 5`（秒）

前端收到 202 后应每 5 秒轮询，通常 2–5 秒内即可收到 200 响应。

### 错误码汇总

| 状态码 | 含义 |
|--------|------|
| 401 | 未认证或 Token 无效/过期 |
| 403 | 用户 Tier 不足 |
| 404 | Ticker 不在股票池中 |
| 409 | 重复操作（如邮箱已注册、自选股已存在） |
| 422 | 请求参数格式错误（如无效 Ticker 格式） |
| 202 | 信号计算中，请轮询 |
