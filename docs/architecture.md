# System Architecture

## English

### Design Philosophy

PenguinAI follows three non-negotiable architectural principles:

1. **Strict layer separation** — Frontend, API, and ML never import from each other directly. Communication happens via HTTP (frontend↔API) and Celery task names (API→ML).
2. **Zero user input to LLM** — The Gemma 4 model receives only backend-assembled structured context. No user free-text input exists anywhere in the system.
3. **Dual-track caching** — Top-100 hot tickers are pre-computed hourly; cold tickers are computed on-demand. The user experience is optimized without wasting GPU compute on unused tickers.

### Service Map

```
Internet
    │
    ▼
┌─────────────┐
│  nginx :80  │  Reverse proxy — routes /api/* → FastAPI, /* → Next.js
└──────┬──────┘
       │
       ├──────────────────────────────────┐
       ▼                                  ▼
┌─────────────────┐              ┌────────────────────┐
│  Next.js :3000  │              │   FastAPI :8000     │
│                 │◄─────────── ►│                     │
│  Dark UI        │   REST API   │  Auth, signals,     │
│  TypeScript     │              │  tickers, watchlist │
└─────────────────┘              └──────────┬──────────┘
                                            │
                                  ┌─────────▼──────────┐
                                  │    TimescaleDB      │
                                  │    :5432            │
                                  │                     │
                                  │  + pgvector (RAG)   │
                                  └─────────┬──────────┘
                                            │
                                  ┌─────────▼──────────┐
                                  │      Redis          │
                                  │      :6379          │
                                  │                     │
                                  │  Celery broker      │
                                  │  Signal TTL cache   │
                                  │  Session store      │
                                  └─────────┬──────────┘
                                            │ Celery tasks
                          ┌─────────────────┴─────────────────┐
                          │                                     │
               ┌──────────▼──────────┐             ┌──────────▼──────────┐
               │   celery_worker     │             │    ml_worker        │
               │   (CPU, 4 threads)  │             │    (GPU, 4090)      │
               │                     │             │                     │
               │  - scrape tasks     │             │  - signal_engine    │
               │  - fundamentals     │             │  - XGBoost / RF     │
               │  - FOMC fetch       │             │  - FinBERT          │
               └─────────────────────┘             │  - Gemma 4 (vLLM)  │
                                                   └─────────────────────┘
                          │
               ┌──────────▼──────────┐
               │   celery_beat       │
               │                     │
               │  Cron scheduler     │
               │  (no compute here)  │
               └─────────────────────┘
                          │
               ┌──────────▼──────────┐
               │   scraper           │
               │                     │
               │  Long-lived runner  │
               │  Playwright/PRAW    │
               └─────────────────────┘
```

### Inter-Service Communication

| From | To | Method | Why |
|------|----|--------|-----|
| Next.js | FastAPI | REST HTTP | Standard web API |
| FastAPI | TimescaleDB | SQLAlchemy async | ORM queries |
| FastAPI | Redis | redis-py (async) | Signal cache read |
| FastAPI | Celery | `send_task(name_string)` | Trigger ML compute without importing ML libs |
| Celery tasks | TimescaleDB | SQLAlchemy async | Read bars, write signals |
| Celery tasks | Redis | redis-py | Update Top-100 list |
| ML worker | vLLM | httpx (local HTTP) | Gemma 4 inference |

### Data Flow: Signal Request

```
User clicks ticker "NVDA"
    │
    ▼
Next.js: GET /api/signals/NVDA
    │
    ▼
FastAPI: SELECT * FROM signal_cache WHERE ticker='NVDA' AND expires_at > now()
    │
    ├─ Cache hit → return 200 + Signal JSON (< 10ms)
    │
    └─ Cache miss
           │
           ▼
       FastAPI: send_task("compute_single_signal", args=["NVDA"])
           │
           ▼
       FastAPI: return 202 { retry_after: 5 }
           │
           ▼
       Frontend: shows loading animation, polls every 5s
           │
           ▼ (background)
       ML Worker receives task:
           1. Load 30-min bars from TimescaleDB
           2. Compute technical features (pandas-ta)
           3. XGBoost.predict_proba() + RF.predict_proba()
           4. Fetch FinBERT scores from social_posts
           5. pgvector RAG: top-5 relevant posts
           6. Fetch celebrity actions + FOMC score
           7. Gemma 4: assemble context + reason → signal JSON
           8. UPSERT into signal_cache
           │
           ▼
       Frontend polls → cache hit → 200 + Signal JSON
```

### Data Flow: Top-100 Pre-computation (Hourly)

```
Celery Beat triggers refresh_top100 (every hour, 9am-5pm ET weekdays)
    │
    ▼
ML Worker: fetch Top-100 list from Redis
    │
    ▼
asyncio.gather: 10 tickers concurrently (each with isolated DB session)
    │
    ▼ (per ticker)
signal_engine.compute(ticker, db)
    → same pipeline as on-demand, but TTL = 1h instead of 4h
    │
    ▼
UPSERT signal_cache (ON CONFLICT DO UPDATE)
    │
    ▼
Frontend user clicks top ticker → cache hit → < 10ms response
```

---

## 中文

### 设计哲学

PenguinAI 遵循三个不可违反的架构原则：

1. **严格层级隔离**：前端、API、ML 层禁止直接相互导入。通信通过 HTTP（前端↔API）和 Celery 任务名字符串（API→ML）进行
2. **零用户输入到 LLM**：Gemma 4 只接收后端硬编码组装的结构化上下文，系统中不存在任何用户自由文本输入入口
3. **双轨缓存**：Top-100 热门股每小时预计算（毫秒响应）；冷门股按需推理（真实加载动画，2-5秒）

### 服务间通信规则

| 发送方 | 接收方 | 方式 | 原因 |
|--------|--------|------|------|
| Next.js | FastAPI | REST HTTP | 标准 Web API |
| FastAPI | Celery | `send_task(任务名字符串)` | 不在 API 进程导入 torch |
| ML Worker | vLLM | httpx 本地 HTTP | Gemma 4 推理 |
| Celery 任务 | TimescaleDB | SQLAlchemy async | 读写数据 |

### 信号请求数据流（中文版）

```
用户点击 "NVDA"
    → FastAPI 查 signal_cache
    ├─ 命中 → 200 + 信号 JSON（毫秒级）
    └─ 未命中
           → 派发 Celery 任务
           → 返回 202 + retry_after: 5
           → 前端轮询
           → ML Worker 后台计算（特征→模型→RAG→Gemma）
           → UPSERT signal_cache
           → 前端再次轮询命中 → 200
```
