# Backend — FastAPI API Gateway

## English

### Overview

The backend is the API gateway for PenguinAI. It handles authentication, signal retrieval, watchlist management, and market data serving. It deliberately contains **no ML logic** — all signal computation is dispatched to the ML layer via Celery task names.

### Structure

```
backend/
├── app/
│   ├── main.py              Entry point — FastAPI app, middleware, router registration
│   ├── api/
│   │   ├── deps.py          Dependency injection: get_db, get_current_user, require_tier
│   │   └── routes/
│   │       ├── signals.py   GET /api/signals/{ticker}, GET /api/signals/top
│   │       ├── auth.py      POST /api/auth/register, /login, GET /me
│   │       ├── tickers.py   GET /api/tickers/search, /universe, /{ticker}
│   │       ├── watchlist.py GET/POST/DELETE /api/watchlist
│   │       ├── market_data.py GET /api/market-data/{ticker}/candles
│   │       └── admin.py     GET /api/admin/pipeline/status (ADMIN tier only)
│   ├── core/
│   │   ├── config.py        Pydantic Settings — all config via environment variables
│   │   ├── database.py      Async SQLAlchemy engine + session factory
│   │   └── security.py      JWT creation/decoding, bcrypt password hashing
│   ├── models/              SQLAlchemy ORM models (mapped to DB tables)
│   │   ├── user.py
│   │   ├── ticker.py
│   │   ├── signal_cache.py
│   │   └── watchlist.py
│   └── schemas/             Pydantic request/response schemas
│       ├── signal.py        SignalResponse, SignalListItem, MLScores, SentimentInfo
│       ├── user.py          RegisterRequest, LoginRequest, TokenResponse, UserResponse
│       └── ticker.py        TickerResponse, TickerSearchResult
├── alembic.ini              Alembic config (points to db/migrations/)
├── requirements.txt
└── Dockerfile
```

### Key Design Decisions

**Authentication**
- JWT Bearer tokens, 7-day expiry
- `get_current_user` dependency raises 401 on invalid/missing token
- `get_optional_user` returns `None` for unauthenticated requests (for public endpoints)
- `require_tier("PRO", "PREMIUM")` factory creates tier-gated dependencies

**Signal Retrieval Flow**
```
GET /api/signals/{ticker}
  ├─ Cache hit (expires_at > now)  → 200 + signal JSON
  └─ Cache miss                    → send_task to ML worker → 202 + retry_after: 5
```
Frontend polls on 202 until it receives 200.

**Tier Access**
Tiers are ranked: `FREE(0) < PRO(1) < PREMIUM(2) < ADMIN(99)`. Each signal row in `signal_cache` carries a `tier_required` field. The `_check_tier_access` function enforces this at read time.

**No ML imports in this process**
Signal computation is triggered by sending a Celery task **by name string** using a bare `Celery(broker=REDIS_URL)` client. This prevents torch/transformers from being loaded in the API process.

### Local Development

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs` when `DEBUG=true`.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | — | JWT signing key (required) |
| `DATABASE_URL` | `postgresql+asyncpg://...` | TimescaleDB connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for Celery broker |
| `DEBUG` | `false` | Enables `/docs` endpoint |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | CORS allowed origins |

### Adding a New Route

1. Create `app/api/routes/your_module.py` with an `APIRouter`
2. Add ORM model in `app/models/` if new table needed
3. Add Pydantic schema in `app/schemas/`
4. Register router in `app/main.py`: `app.include_router(your_module.router, prefix="/api/...")`
5. Create Alembic migration: `cd backend && alembic revision --autogenerate -m "add your_table"`

### Running Migrations

```bash
cd backend
# Generate migration from model changes
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

---

## 中文

### 模块概述

后端是 PenguinAI 的 API 网关层，负责用户认证、信号读取、自选股管理和 K 线数据服务。它**不包含任何 ML 逻辑** — 信号计算通过 Celery 任务名字符串派发到 ML 层。

### 关键设计决策

**认证机制**
- JWT Bearer Token，7 天有效期
- `get_current_user`：未认证直接返回 401
- `get_optional_user`：未认证返回 `None`（用于公开端点）
- `require_tier("PRO")` 工厂函数生成分层权限依赖

**信号获取流程**
```
GET /api/signals/{ticker}
  ├─ 缓存命中（expires_at > 当前时间）→ 200 + 信号 JSON（毫秒级）
  └─ 缓存未命中                       → 触发 Celery 任务 → 202 + retry_after: 5
```
前端收到 202 后每 5 秒轮询直到获得 200。

**API 进程不导入 ML 库**
触发 Celery 任务时只使用任务名字符串 + 裸 `Celery(broker=...)` 客户端，防止 torch/transformers 在 API 进程中被加载，避免启动内存暴涨。

### 新增路由步骤

1. 在 `app/api/routes/` 创建新路由文件
2. 如需新表：在 `app/models/` 创建 ORM 模型
3. 在 `app/schemas/` 创建 Pydantic Schema
4. 在 `app/main.py` 注册路由
5. 执行 `alembic revision --autogenerate -m "描述"` 生成迁移文件
