# API Reference

## English

Base URL: `http://localhost:8000/api` (local) · `https://your-domain.com/api` (production)

Authentication: `Authorization: Bearer <access_token>` header (JWT)

---

### Authentication

#### `POST /auth/register`
Create a new user account. Sends a verification email (logged in DEBUG mode). The
returned JWT is valid immediately; email verification is not required to log in.

**Rate limit**: 5 / hour per IP

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
In DEBUG mode the response also carries `_debug_verify_token`.

**Errors**: `409 Conflict` (email already exists), `429` (rate limited)

---

#### `POST /auth/login`
Authenticate and receive a JWT token.

**Rate limit**: 10 / minute per IP + 20 / hour per account (keyed by email hash)

**Request**
```json
{ "email": "user@example.com", "password": "yourpassword" }
```

**Response** `200 OK`
```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

**Errors**: `401 Unauthorized` (invalid credentials), `429` (rate limited)

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

#### `POST /auth/verify-email`
Verify an email address with the token from the verification link.

**Request**
```json
{ "token": "eyJ..." }
```

**Response** `200 OK`
```json
{ "message": "Email verified successfully." }
```
(or `"Email already verified."` if already done)

**Errors**: `400 Bad Request` (invalid or expired token)

---

#### `POST /auth/resend-verification`
Re-send the verification email for the current user.

**Auth**: Required

**Response** `200 OK`
```json
{ "message": "Verification email sent." }
```
Returns `"Email already verified."` when nothing to send. In DEBUG mode the
response also carries `_debug_verify_token`.

---

#### `POST /auth/forgot-password`
Request a password-reset link. Always returns the same message regardless of
whether the email exists (no account enumeration).

**Rate limit**: 5 / hour per IP

**Request**
```json
{ "email": "user@example.com" }
```

**Response** `200 OK`
```json
{ "message": "If this email is registered, you will receive a reset link shortly." }
```

---

#### `POST /auth/reset-password`
Reset the password using the token from the reset link. Increments
`token_version`, invalidating all existing sessions.

**Rate limit**: 5 / hour per IP

**Request**
```json
{ "token": "eyJ...", "password": "newStrongPass1!" }
```

**Response** `200 OK`
```json
{ "message": "Password has been reset successfully." }
```

**Errors**: `400 Bad Request` (invalid or expired token)

---

#### `POST /auth/change-password`
Change the password for the current user. Increments `token_version` (invalidates
all other sessions) and returns a fresh JWT.

**Auth**: Required

**Request**
```json
{ "current_password": "oldPass1!", "new_password": "newStrongPass1!" }
```

**Response** `200 OK`
```json
{ "message": "Password changed successfully.", "access_token": "eyJ..." }
```

**Errors**: `400 Bad Request` (current password incorrect)

---

### OAuth (Sign in with Google / Apple)

Provider sign-in is browser-redirect based. `{provider}` ∈ `google` · `apple`.
When a provider is not configured, the start endpoint returns `503` and the
callbacks redirect to the frontend with an `error` fragment.

#### `GET /auth/oauth/{provider}`
Begin the OAuth flow. Issues a signed `state`/`nonce` and redirects the browser to
the provider's authorization page.

**Response** `302 Found` → provider authorize URL

**Errors**: `404` (unknown provider), `503` (provider not configured)

---

#### `GET /auth/oauth/{provider}/callback`
#### `POST /auth/oauth/{provider}/callback`
Provider redirect target (`GET` for Google, `POST` form_post for Apple). Verifies
the `state`/`id_token`, then finds-or-creates the user (links to an existing
email/password account on email match; OAuth emails are pre-verified) and issues a
JWT.

**Query / form params**: `code`, `state`, `error` (Apple also sends a one-time
`user` JSON payload with the display name on first consent)

**Response** `302 Found` → `{FRONTEND_BASE_URL}/auth/callback#access_token=eyJ...`
(the token rides in the URL fragment so it is never logged or sent in `Referer`).
On any failure it redirects with `#error=<reason>` instead (e.g. `oauth_unavailable`,
`invalid_state`, `oauth_failed`, `oauth_no_email`).

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

#### `GET /market-data/status`
Global "is the US market open right now" — the single source of truth the frontend
uses for the LIVE/CLOSED badge and live-poll cadence. Public, cached 5s
(`Cache-Control: public, max-age=5`).

**Response** `200 OK` — market status object (open flag, session phase, etc.).

---

#### `POST /market-data/{ticker}/warm`
On-demand: pull a freshly opened ticker's recent 1-min bars from Massive into
`market_data_1min` so its chart fills immediately. Idempotent.

**Response** `200 OK`
```json
{ "ticker": "NVDA", "warmed_bars": 120 }
```

---

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

#### `GET /celebrity-holdings/{celebrity}/top-holdings`
Distinct tickers held by one celebrity, each with its latest action and trade count.

**Path params**: `celebrity` — lowercase slug

**Query params**: `limit` — int, default 30, max 100

**Response** `200 OK`
```json
[
  {
    "ticker": "AAPL",
    "ticker_name": "Apple Inc.",
    "latest_action": "HOLD",
    "last_activity": "2026-05-15T00:00:00+00:00",
    "shares": 400000000,
    "value_usd": 85720000000,
    "trade_count": 6
  }
]
```

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

### News

All news endpoints are public. Articles share a unified shape:
`{ id, headline, summary, source, url, image, datetime (unix sec), tickers[], category, sentiment, sentiment_score }`.
Source priority: Massive → Google News RSS → Finnhub. FinBERT scores
DB-stored and cold-ticker articles (`sentiment` ∈ `positive` · `negative` · `neutral`).

#### `GET /news/market`
General market news for the feed page (cached 5 min).

**Query params**: `limit` — int, default 30, max 100

**Response** `200 OK` — array of article objects.

---

#### `GET /news/hot`
Pre-stored hot-ticker news from the DB (last 7 days). Optionally filter by ticker;
falls back to on-demand API fetch when the DB is empty.

**Query params**:
| Param | Type | Default | Max |
|-------|------|---------|-----|
| `limit` | int | 50 | 200 |
| `ticker` | string | — | — |

**Response** `200 OK` — array of article objects.

**Errors**: `422` (invalid ticker format)

---

#### `GET /news/{ticker}`
News for a specific ticker. Hot tickers served from the DB; cold tickers fetched
on-demand via the 3-tier fallback, FinBERT-scored, and cached 10 min.

**Path params**: `ticker` — uppercase symbol

**Query params**:
| Param | Type | Default | Max |
|-------|------|---------|-----|
| `days` | int | 7 | 30 |
| `limit` | int | 20 | 50 |

**Response** `200 OK` — array of article objects.

**Errors**: `422` (invalid ticker format)

---

### Pinned Signals

User-customizable "Top Signals" ticker list (0–12 tickers).

#### `GET /pinned-signals`
Return the current user's pinned tickers, ordered by position.

**Auth**: Required

**Response** `200 OK`
```json
["AAPL", "MSFT", "NVDA"]
```

---

#### `PUT /pinned-signals`
Replace the entire pinned list. Each ticker is validated against the universe;
duplicates are de-duped (uppercased).

**Auth**: Required

**Request**
```json
{ "tickers": ["AAPL", "MSFT", "NVDA"] }
```

**Response** `200 OK` — the stored ordered ticker list.

**Errors**: `404` (a ticker is not in the universe), `422` (more than 12 tickers)

---

### FOMC

All FOMC endpoints are public and backed by a short in-process TTL cache. They read
`fomc_statements`, `fomc_fed_funds_rate`, `fomc_rate_probabilities`, `bars_1d` (SPY),
and `news_articles` (`ticker='FOMC'`), with live fallbacks where noted.

#### `GET /fomc/statements`
All FOMC statements with hawk/dove scores, most recent first.

**Query params**: `limit` — int, 1–200 (default from `FOMC_DEFAULT_STATEMENTS_LIMIT`)

**Response** `200 OK`
```json
[
  { "date": "2026-04-29", "datetime": 1777334400, "hawk_dove_score": -0.2,
    "summary": "...", "document_url": "https://www.federalreserve.gov/..." }
]
```

---

#### `GET /fomc/trend`
Hawk/dove score time-series for charts (oldest first).

**Query params**: `limit` — int, 1–50 (default from `FOMC_DEFAULT_TREND_LIMIT`)

**Response** `200 OK` — `[{ "date": "2026-04-29", "score": -0.2 }]`

---

#### `GET /fomc/next-meeting`
Next scheduled FOMC meeting date and countdown.

**Response** `200 OK`
```json
{ "next_meeting": "2026-06-17", "days_until": 7 }
```

---

#### `GET /fomc/schedule`
Meeting schedule with a configurable past/future window.

**Query params**: `past` (0–50), `future` (0–50) — defaults from settings.

**Response** `200 OK` — `[{ "date": "2026-04-29", "past": true }]`

---

#### `GET /fomc/rate-history`
Federal funds target rate over time (DB table, hardcoded fallback).

**Query params**: `years` — int, 1–30 (default from settings)

**Response** `200 OK` — `[{ "date": "2025-12-10", "rate_low": 4.25, "rate_high": 4.5 }]`

---

#### `GET /fomc/market-reaction`
SPY return on each FOMC meeting day (close/prev_close − 1), with the rate in effect.

**Query params**: `limit` — int, 1–100 (default from settings)

**Response** `200 OK`
```json
[ { "date": "2026-04-29", "spy_return_pct": 0.83, "spy_close": 542.1, "rate_low": 4.25, "rate_high": 4.5 } ]
```

---

#### `GET /fomc/diff`
Sentence-level diff between a statement and the previous one.

**Query params**: `date` (required) — `YYYY-MM-DD`

**Response** `200 OK`
```json
{ "current_date": "2026-04-29", "previous_date": "2026-03-18",
  "diff": [ { "type": "unchanged", "text": "..." }, { "type": "added", "text": "..." } ] }
```
`type` ∈ `unchanged` · `added` · `removed`. Returns `{ "error": ... }` for an
invalid date or missing statement.

---

#### `GET /fomc/news`
Fed/FOMC-related news (DB rows tagged `ticker='FOMC'`, live RSS fallback).

**Query params**: `limit` — int, 1–50 (default 10)

**Response** `200 OK` — array of news article objects (same shape as `/news/*`).

---

#### `GET /fomc/rate-probabilities`
CME FedWatch implied probabilities for the next meeting (DB snapshot, live fallback).

**Response** `200 OK`
```json
[ { "meeting_date": "2026-06-17", "target_rate_low": 4.0, "target_rate_high": 4.25, "probability": 0.62 } ]
```

---

### Fear & Greed

All endpoints public, backed by a 5-minute in-process cache. Reads the
`fear_greed_index` + `volatility_index` tables (CNN + CBOE/Yahoo/FRED).

#### `GET /fear-greed`
Current index reading: score, rating, the 7 components, and the value at previous
close / 1 week / 1 month / 1 year ago.

**Response** `200 OK`
```json
{
  "score": 62.5,
  "rating": "greed",
  "label": "Greed",
  "updated_at": "2026-06-10T00:00:00+00:00",
  "source": "cnn",
  "previous": { "close": 60.1, "week": 55.0, "month": 48.2, "year": 70.4 },
  "components": [ ... ]
}
```
`label` ∈ `Extreme Fear` · `Fear` · `Neutral` · `Greed` · `Extreme Greed`.

---

#### `GET /fear-greed/history`
Daily Fear & Greed score series (ascending).

**Query params**: `days` — int, 7–3650 (default 365)

**Response** `200 OK` — `[{ "date": "2026-06-09", "score": 60.1, "rating": "greed" }]`

---

#### `GET /fear-greed/volatility`
Daily OHLC series for a volatility index (ascending) + latest value and change.

**Query params**:
| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `symbol` | string | `VIX` | `VIX` or `VVIX` only |
| `days` | int | 365 | 7–20000 |

**Response** `200 OK`
```json
{
  "symbol": "VIX",
  "latest": 14.2,
  "change_pct": -3.1,
  "bars": [ { "time": 1749513600, "date": "2026-06-09", "open": 14.5, "high": 14.9, "low": 14.0, "close": 14.6 } ]
}
```

**Errors**: `422` (symbol not VIX/VVIX)

---

### Admin (ADMIN tier only)

> 完整文档见 [admin-dashboard.md](./admin-dashboard.md)

#### `GET /admin/health/overview`
全局服务健康交通灯（TimescaleDB / Redis / Celery / 实时流等）。

**Response** `200 OK`
```json
{
  "overall": "healthy",
  "checked_at": "2026-06-09T15:42:00Z",
  "services": [
    { "name": "timescaledb", "status": "healthy", "latency_ms": 2.3, "detail": "8 connections, pool: 3/40 active" },
    { "name": "redis", "status": "healthy", "latency_ms": 0.8, "detail": "PONG, mem=12.5M" }
  ]
}
```

---

#### `GET /admin/health/endpoints`
枚举所有注册路由 + 探针检测关键端点延迟。

---

#### `GET /admin/db/health`
数据库连接池状态、表大小/行数/最新时间戳、总 DB 大小。

---

#### `GET /admin/tasks/status`
Celery 定时任务上次执行信息、队列深度、Worker 在线状态。

---

#### `GET /admin/datasources/status`
实时数据源连接状况（IBKR/Finnhub/Massive）+ 各表数据新鲜度。

---

#### `GET /admin/models/performance`
ML 模型文件信息、Feature Importance、Signal 分布。

---

#### `GET /admin/users/stats`
用户聚合统计（总数、分 tier、已验证、今日/本周注册）。

---

#### `GET /admin/users`
分页用户列表（支持 `search` / `tier` 筛选）。

**Query params**: `page`, `per_page` (default 20), `search`, `tier`

---

#### `PATCH /admin/users/{user_id}`
修改用户 tier 或封禁状态。不能修改自己。

**Request body** (all optional):
```json
{ "tier": "PRO", "is_active": false }
```

---

#### `POST /admin/actions/{action}`
手动触发 Celery 任务。

**Path params**: `action` ∈ `refresh-signals` · `retrain-models` · `scrape-social` · `fetch-earnings` · `fetch-celebrities` · `fetch-news` · `validate-symbols`

**Response** `200 OK`
```json
{ "triggered": true, "task_id": "abc-123", "task_name": "ml.tasks.hourly_signal_cache.refresh_top100" }
```

---

#### `GET /admin/actions/task/{task_id}`
查询已触发任务的执行状态。

**Response** `200 OK`
```json
{ "task_id": "abc-123", "status": "SUCCESS", "result": null }
```

---

#### `GET /admin/logs`
查询系统日志（内存 ring buffer）。

**Query params**: `lines` (default 100, max 1000), `level` (default `INFO`)

**Response** `200 OK`
```json
{
  "entries": [
    { "timestamp": "2026-06-09T15:42:00Z", "level": "ERROR", "logger": "realtime.ibkr", "message": "heartbeat timeout" }
  ],
  "total_buffered": 1843,
  "showing": 100,
  "min_level": "ERROR"
}
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
