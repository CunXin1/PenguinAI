# Backend — FastAPI API Gateway

## Overview

The backend is the API gateway for PenguinAI. It handles authentication (password reset flow + Google/Apple OAuth), signal retrieval, watchlist management, market-data serving, the earnings calendar, news headlines, FOMC statements, the Fear & Greed Index, celebrity/smart-money holdings, market status (NYSE calendar-aware), realtime ingestion supervision, and the user symbol-request (data-demand) queue. It deliberately contains **no ML logic** — all signal computation is dispatched to the ML layer via Celery task names.

## Project Structure

```
backend/
├── app/
│   ├── main.py                  Entry point — FastAPI app, CORS, lifespan, SupervisorWatchdog
│   ├── conftest.py              Shared test fixtures (SQLite in-memory, PG-type patches, users/tickers)
│   ├── api/
│   │   ├── deps.py              Dependency injection: get_db, get_current_user, get_optional_user, require_tier
│   │   └── routes/
│   │       ├── auth.py          Register, login, me, forgot/reset/change password, Google/Apple OAuth
│   │       ├── signals.py       GET /api/signals/{ticker}, GET /api/signals/top
│   │       ├── tickers.py       GET /api/tickers/search, /universe, /{ticker}
│   │       ├── watchlist.py     GET/POST/DELETE /api/watchlist
│   │       ├── market_data.py   Candles, series, quotes, mini, heatmap, market status, on-demand warm
│   │       ├── earnings.py      GET /api/earnings/calendar, /api/earnings/{ticker}
│   │       ├── celebrity_holdings.py  GET /api/celebrity-holdings (SEC 13F / ARK / Congress / Trump DJT)
│   │       ├── news.py          GET /api/news (per-ticker FinBERT-scored headlines)
│   │       ├── pinned_signals.py  GET/PUT /api/pinned-signals (Top Signals customization)
│   │       ├── fomc.py          GET /api/fomc (FOMC statements + hawk/dove scores)
│   │       ├── fear_greed.py    GET /api/fear-greed (Fear & Greed Index + VIX/VVIX)
│   │       ├── symbols.py       POST /api/symbols/request, GET /api/symbols/requests (ADMIN)
│   │       ├── admin.py         GET /api/admin/pipeline/status, POST /api/admin/cache/refresh (ADMIN)
│   │       └── tests/           Route-level integration tests
│   │           ├── conftest.py
│   │           ├── test_auth.py
│   │           ├── test_signals.py
│   │           ├── test_watchlist.py
│   │           ├── test_tickers_symbols.py
│   │           ├── test_market_data.py
│   │           └── test_admin.py
│   ├── core/
│   │   ├── config.py            Pydantic Settings — all config via environment variables
│   │   ├── database.py          Async SQLAlchemy engine + session factory (asyncpg / aiosqlite)
│   │   ├── security.py          JWT creation/decoding, bcrypt password hashing, reset tokens
│   │   ├── market_clock.py      NYSE session detection via exchange_calendars, tick-advancing fallback
│   │   ├── rate_limit.py        Redis-backed sliding-window rate limiter (INCR + EXPIRE)
│   │   └── tests/
│   │       └── test_core.py     Unit tests for market_clock, security, JWT
│   ├── models/                  SQLAlchemy ORM models (mapped to DB tables)
│   │   ├── user.py
│   │   ├── ticker.py
│   │   ├── signal_cache.py
│   │   ├── symbol_request.py    Data-demand queue (user-requested uncovered symbols)
│   │   └── watchlist.py
│   └── schemas/                 Pydantic request/response schemas
│       ├── signal.py            SignalResponse, SignalListItem, MLScores, SentimentInfo
│       ├── user.py              RegisterRequest, LoginRequest, TokenResponse, UserResponse,
│       │                        ForgotPasswordRequest, ResetPasswordRequest, ChangePasswordRequest
│       ├── symbol_request.py    SymbolRequestInput, SymbolRequestResult, SymbolRequestRow
│       └── ticker.py            TickerResponse, TickerSearchResult
├── alembic.ini
├── requirements.txt
├── Dockerfile
└── scripts/
```

## API Endpoints

### Auth (`/api/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/register` | No | Create account, returns JWT. Rate-limited: 5/hour per IP |
| POST | `/api/auth/login` | No | Authenticate, returns JWT. Rate-limited: 10/min per IP |
| GET | `/api/auth/me` | Yes | Return current user profile |
| POST | `/api/auth/forgot-password` | No | Generate password reset token (always returns 200). Rate-limited: 5/hour |
| POST | `/api/auth/reset-password` | No | Reset password using a token (1-hour expiry). Rate-limited: 5/hour |
| POST | `/api/auth/change-password` | Yes | Change password (requires current password) |
| GET | `/api/auth/oauth/{provider}` | No | Start Google/Apple sign-in (302 to provider). 503 if the provider isn't configured |
| GET·POST | `/api/auth/oauth/{provider}/callback` | No | OAuth callback → find-or-create user, issue JWT, 302 to frontend. 503 if the provider isn't configured |

### Signals (`/api/signals`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/signals/top` | No | Pre-computed Top-N signals ordered by confidence (limit param, max 200) |
| GET | `/api/signals/{ticker}` | Optional | Signal for a ticker: 200 cache hit, 202 triggers compute, 404 not in universe. `poll=true` skips re-trigger |

### Tickers (`/api/tickers`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/tickers/search` | No | Search by ticker prefix or name substring (q param, limit 20) |
| GET | `/api/tickers/universe` | No | Browse active tickers with optional `sector`/`tag` filter and pagination |
| GET | `/api/tickers/{ticker}` | No | Single ticker detail |

### Watchlist (`/api/watchlist`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/watchlist` | Yes | User's watchlist tickers with latest cached signals |
| POST | `/api/watchlist/{ticker}` | Yes | Add ticker to watchlist (409 if duplicate, 404 if unknown) |
| DELETE | `/api/watchlist/{ticker}` | Yes | Remove ticker from watchlist (idempotent, 204) |

### Market Data (`/api/market-data`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/market-data/status` | No | Is the US market open right now (used by frontend LIVE/CLOSED badge). 5s server cache |
| GET | `/api/market-data/{ticker}/candles` | No | OHLCV bars for charting (timeframe: 1min/30min/1day, days: 1-365) |
| GET | `/api/market-data/{ticker}/series` | No | OHLC series for range (1D/1W/1M/3M/1Y), time_bucket-aggregated. Falls back to 30min/daily bars if no minute data |
| GET | `/api/market-data/quotes` | No | Batch latest price + % change for comma-separated tickers (max 60) |
| GET | `/api/market-data/mini` | No | Index-strip data: price + % change + intraday spark per ticker (max 12) |
| GET | `/api/market-data/heatmap` | No | Market-cap heatmap tiles + index ETFs (SPY/QQQ/IWM), period: 1D/1W/1M/3M/1Y |
| POST | `/api/market-data/{ticker}/warm` | No | On-demand: pull recent 1-min bars from Massive into market_data_1min for an uncovered symbol |

### Earnings (`/api/earnings`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/earnings/calendar` | No | Earnings calendar for a date window (default: today-7d to today+30d) |
| GET | `/api/earnings/{ticker}` | No | Earnings history for one ticker (newest first, limit param, max 40) |

### Symbols (`/api/symbols`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/symbols/request` | No | Request coverage for an uncovered symbol (deduped, bumps count on repeat) |
| GET | `/api/symbols/requests` | ADMIN | List the data-demand queue, most-requested first |

### Admin (`/api/admin`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/admin/pipeline/status` | ADMIN | DB row counts for pipeline health monitoring |
| POST | `/api/admin/cache/refresh` | ADMIN | Manually trigger Top-100 signal cache refresh via Celery |

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Returns `ok`/`degraded` status, app version, and realtime supervisor health |

## Authentication

**JWT Bearer tokens**, HS256-signed with `SECRET_KEY`, 7-day expiry (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`).

- `get_current_user` — decodes token, looks up user, raises 401 on invalid/missing token
- `get_optional_user` — returns `None` for unauthenticated requests (for public endpoints that optionally personalize)
- `require_tier("PRO", "PREMIUM")` — factory that creates tier-gated dependencies. ADMIN tier always passes

**Password validation rules** (enforced by Pydantic validators on `RegisterRequest`, `ResetPasswordRequest`, `ChangePasswordRequest`):

- Minimum 8 characters, maximum 72 (bcrypt limit)
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character

**Password reset flow:**

1. `POST /api/auth/forgot-password` with email — always returns 200 (no email-enumeration leak). Generates a JWT with `purpose: "reset"` and 1-hour expiry
2. `POST /api/auth/reset-password` with `{token, password}` — validates the reset token and updates the password
3. Email delivery: sent via SMTP when `EMAIL_BACKEND=smtp`; otherwise logged server-side (dev default). See `core/email.py`

**Timing-safe login:** The login endpoint always runs bcrypt (against a dummy hash if the user doesn't exist) to prevent timing side-channel attacks that reveal whether an email is registered.

**Rate limiting:** Redis-backed sliding-window limiter (`INCR` + `EXPIRE`). Degrades gracefully when Redis is unavailable (requests pass through with a warning). Applied to login (10/min), register (5/hour), forgot-password (5/hour), reset-password (5/hour).

## Market Clock

`app/core/market_clock.py` provides a single source of truth for "is the US market open right now", shared by `/api/market-data/status` and the heatmap endpoint.

**Two detection methods** (market is considered open if either is true):

1. **`is_regular_session(now_utc)`** — Uses the `exchange_calendars` library (`XNYS` calendar) which knows about all NYSE holidays, early closes, and special sessions. Checks whether `now_utc` falls between session open and close times.

2. **`ticks_advancing(latest_tick)`** — Live-feed freshness check. **Stateless**: returns true when the newest `market_data_1min` bar is within the last 360 seconds of wall-clock time. Because the answer derives only from the DB row (no per-process tick memory), every uvicorn worker (`WEB_CONCURRENCY=4`) agrees, so the LIVE/CLOSED badge can't flicker between workers, and a freshly-started process reports correctly without waiting for the next bar. A stalled feed ages out of the window. (`get_market_status` also exposes this as `feed_live`, which the frontend renders as a "DELAYED" badge when the session is open but the feed has stalled.)

**`is_early_close(date)`** — Returns true if a given date is an NYSE early-close session (close before 16:00 ET).

## SupervisorWatchdog

`_SupervisorWatchdog` in `main.py` manages the realtime data ingestion subprocess (`data.ingestion.realtime.supervisor`).

- Starts on app lifespan startup, stops on shutdown
- Controlled by `REALTIME_ENABLED` env var (default: `true`)
- Auto-restarts on crash with exponential backoff (1s, 2s, 4s, ... up to 60s)
- Max 10 restarts within a 1-hour window before giving up
- Parses `HEALTH:` JSON lines from the subprocess stdout for health reporting
- Health status exposed via `GET /health` endpoint

## Signal Retrieval Flow

```
GET /api/signals/{ticker}
  ├─ Not in universe (Ticker table) → 404 (reason: not_in_universe | delisted)
  ├─ Cache hit (expires_at > now)   → 200 + SignalResponse JSON
  └─ Cache miss                     → send_task to ML worker → 202 + retry_after: 5
```

Frontend polls on 202 until it receives 200. The `poll=true` query param skips re-triggering the Celery task (deduplication). In-flight tracking prevents the same ticker from being re-dispatched within 5 minutes.

**Tier access:** Tiers are ranked `FREE(0) < PRO(1) < PREMIUM(2) < ADMIN(99)`. Each signal row carries a `tier_required` field. `_check_tier_access` enforces this at read time — anonymous users are treated as FREE.

**No ML imports in the API process:** Signal computation is triggered by `Celery.send_task()` with a task name string and a bare `Celery(broker=REDIS_URL)` client. This prevents torch/transformers from being loaded in the API process.

## Testing

Tests live inside each module (co-located with the code they test):

```
app/
├── conftest.py                        Shared fixtures: SQLite in-memory DB, PG-type patches,
│                                      test users (FREE/PRO/ADMIN), test ticker, test signal
├── api/routes/tests/
│   ├── conftest.py                    Route-specific fixture overrides
│   ├── test_auth.py                   Register, login, me, token validation, OAuth (Google/Apple, implemented; 503 when unconfigured)
│   ├── test_signals.py                Top signals, cache hit/miss, poll dedup, universe gate,
│   │                                  tier gating (FREE blocked, PRO allowed, ADMIN bypass)
│   ├── test_watchlist.py              CRUD lifecycle, auth gating, signal attachment
│   ├── test_tickers_symbols.py        Search, universe browsing, symbol request + admin list
│   ├── test_market_data.py            Status, candles, quotes, mini, series, heatmap (mocked DB)
│   └── test_admin.py                  Pipeline status + cache refresh (admin gating, Celery mock)
└── core/tests/
    └── test_core.py                   market_clock (regular session, weekend, after-hours),
                                       password hashing roundtrip, JWT encode/decode
```

**Test infrastructure:** Uses SQLite + aiosqlite as an in-memory test database. PostgreSQL-specific column types (UUID, ARRAY, TIMESTAMP WITH TIME ZONE) are patched at the DDL/compilation level so SQLAlchemy can create identical tables in SQLite. Market-data tests that depend on TimescaleDB-specific SQL (time_bucket, DISTINCT ON, LATERAL) use a mocked `AsyncSession`.

**Running tests:**

```bash
# All backend tests
make test-backend

# Single test file
python3 -m pytest backend/app/api/routes/tests/test_auth.py -v

# Single test
python3 -m pytest backend/app/api/routes/tests/test_signals.py::test_get_signal_cache_hit -v
```

pytest config is in the repo-root `pyproject.toml` (`asyncio_mode=auto` — async tests need no decorator).

## Configuration

All configuration is via environment variables, loaded by Pydantic Settings (`app/core/config.py`). Reads from `.env` file automatically.

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | — | JWT signing key (set in production; auto-generates an ephemeral key + logs CRITICAL if unset) |
| `DEBUG` | `false` | Enables `/docs` and `/redoc` endpoints, sets SQLAlchemy echo |
| `DATABASE_URL` | `postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai` | TimescaleDB connection |
| `DATABASE_POOL_SIZE` | `40` | SQLAlchemy connection pool size |
| `DATABASE_MAX_OVERFLOW` | `20` | SQLAlchemy max overflow connections |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for Celery broker + rate limiter |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | CORS allowed origins (comma-separated or JSON array) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` (7 days) | JWT access token lifetime |
| `REALTIME_ENABLED` | `true` | Start the realtime ingestion supervisor subprocess |
| `POLYGON_API_KEY` | — | Polygon.io API key (legacy) |
| `MASSIVE_API_KEY` | — | Massive.com API key |
| `FINNHUB_API_KEY` | — | Finnhub API key (earnings calendar) |
| `IBKR_HOST` / `IBKR_PORT` / `IBKR_CLIENT_ID` | `127.0.0.1` / `7497` / `1` | Interactive Brokers connection |
| `GEMMA_MODEL_PATH` / `GEMMA_API_URL` / `GEMMA_API_KEY` | — | Gemma 4 model configuration |
| `FINBERT_MODEL` | `ProsusAI/finbert` | FinBERT model name |
| `OAUTH_REDIRECT_BASE` | `http://localhost:8000` | Base URL for OAuth callback redirect (`{base}/api/auth/oauth/{provider}/callback`) |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Frontend base URL OAuth redirects back to after issuing a JWT |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | — | "Sign in with Google" OAuth credentials |
| `APPLE_CLIENT_ID` / `APPLE_TEAM_ID` / `APPLE_KEY_ID` / `APPLE_PRIVATE_KEY` | — | "Sign in with Apple" OAuth credentials (Services ID, team/key IDs, `.p8` PEM) |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | — | Reddit API (planned) |

**SECRET_KEY safety:** When the SECRET_KEY is insecure or empty, `_check_secret_key` generates an ephemeral random key (tokens reset on restart). It never raises — instead it logs CRITICAL in non-DEBUG mode and WARNING in DEBUG mode. Always set a strong `SECRET_KEY` in production.

## Local Development

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs` when `DEBUG=true`.

## Dependencies

Key packages in `requirements.txt`:

- **fastapi** + **uvicorn** — ASGI web framework + server
- **sqlalchemy[asyncio]** + **asyncpg** — Async ORM + PostgreSQL driver
- **pydantic** + **pydantic-settings** — Schema validation + env config
- **python-jose** — JWT encoding/decoding
- **bcrypt** (via passlib) — Password hashing
- **celery[redis]** + **redis** — Task queue client + rate limiter store
- **exchange-calendars** + **pandas** — NYSE holiday/session calendar
- **httpx** — Async HTTP client
- **alembic** — Database migrations

---

## 中文

### 模块概述

后端是 PenguinAI 的 API 网关层，负责用户认证（含密码重置流程）、信号读取、自选股管理、K 线数据服务、收益日历、市场状态检测（NYSE 日历感知）和实时数据采集监控。它**不包含任何 ML 逻辑** — 信号计算通过 Celery 任务名字符串派发到 ML 层。

### 关键设计决策

**认证机制**
- JWT Bearer Token，7 天有效期，HS256 签名
- `get_current_user`：未认证直接返回 401
- `get_optional_user`：未认证返回 `None`（用于公开端点）
- `require_tier("PRO")` 工厂函数生成分层权限依赖，ADMIN 始终通过
- 密码强度验证：最少 8 位，需包含大写、小写、数字和特殊字符
- 密码重置：JWT 令牌（1 小时有效期），忘记密码接口始终返回 200（防止邮箱枚举）
- 登录接口始终执行 bcrypt 比对（防止计时侧信道攻击）

**市场状态检测**
- 使用 `exchange_calendars` 库（XNYS 日历），包含所有 NYSE 假日、提前收盘等
- `ticks_advancing` 为无状态实时性检测：最新 1 分钟数据在过去 360 秒内即判定 feed 存活；因结果只取决于数据库行，4 个 uvicorn worker 答案一致，徽章不会跳变
- `/api/market-data/status` 是前端 LIVE/CLOSED 徽章的唯一数据来源；`feed_live=false`（开盘但 feed 停滞）时前端显示 DELAYED 徽章

**实时数据采集监控 (SupervisorWatchdog)**
- 在 FastAPI lifespan 中启动 `data.ingestion.realtime.supervisor` 子进程
- 崩溃后自动重启（指数退避），1 小时内最多重启 10 次
- 通过 `REALTIME_ENABLED` 环境变量控制开关

**信号获取流程**
```
GET /api/signals/{ticker}
  ├─ 不在覆盖范围（Ticker 表）→ 404（原因：not_in_universe | delisted）
  ├─ 缓存命中（expires_at > 当前时间）→ 200 + 信号 JSON（毫秒级）
  └─ 缓存未命中                       → 触发 Celery 任务 → 202 + retry_after: 5
```
前端收到 202 后每 5 秒轮询直到获得 200。`poll=true` 参数跳过重复触发。

**API 进程不导入 ML 库**
触发 Celery 任务时只使用任务名字符串 + 裸 `Celery(broker=...)` 客户端，防止 torch/transformers 在 API 进程中被加载。

**限流**
基于 Redis 的滑动窗口限流器（INCR + EXPIRE）。Redis 不可用时优雅降级（放行请求并输出警告）。

### 测试

测试与代码共存于各模块内部：
- `app/api/routes/tests/` — 路由集成测试（auth、signals、watchlist、tickers/symbols、market_data、admin）
- `app/core/tests/` — 核心模块单元测试（market_clock、security、JWT）

使用 SQLite 内存数据库，PG 特有类型（UUID、ARRAY、带时区时间戳）在 DDL 层面做了 patch。

```bash
make test-backend          # 运行全部后端测试
```

### 新增路由步骤

1. 在 `app/api/routes/` 创建新路由文件
2. 如需新表：在 `app/models/` 创建 ORM 模型
3. 在 `app/schemas/` 创建 Pydantic Schema
4. 在 `app/main.py` 注册路由
5. 在 `app/api/routes/tests/` 添加测试
6. 执行 `alembic revision --autogenerate -m "描述"` 生成迁移文件
