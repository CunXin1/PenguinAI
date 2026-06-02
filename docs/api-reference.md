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
Get OHLCV bars for charting.

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
    { "time": "2026-05-30T09:30:00Z", "open": 900.0, "high": 915.0, "low": 898.0, "close": 910.0, "volume": 5200000 },
    ...
  ]
}
```

---

### Admin (ADMIN tier only)

#### `GET /admin/pipeline/status`
Get data pipeline health metrics.

**Response** `200 OK`
```json
{
  "db_stats": {
    "bars_30min": 170000000,
    "bars_1min": 500000,
    "social_posts": 85000,
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
