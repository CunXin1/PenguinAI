# System Architecture

## English

### Design Philosophy

PenguinAI follows three non-negotiable architectural principles:

1. **Strict layer separation** — Frontend, API, and ML never import from each other directly. Communication happens via HTTP (frontend↔API) and Celery task names (API→ML).
2. **Zero user input to LLM** — The Gemma 4 model receives only backend-assembled structured context. No user free-text input exists anywhere in the system.
3. **Dual-track caching** — Top-100 hot tickers are pre-computed hourly; cold tickers are computed on-demand. The user experience is optimized without wasting GPU compute on unused tickers.

> **Implementation status.** This map is the target design. Live today: nginx,
> Next.js, FastAPI, TimescaleDB (`bars_30m` ~236M rows loaded), Redis, and the
> Celery workers/beat (data ingestion: Massive, Finnhub, IBKR). `celebrity_holdings`
> and `fomc_statements` ARE auto-populated by background schedulers wired into the
> FastAPI lifespan (`_run_celebrity_scheduler` — startup + daily 19:00 ET, loaders
> in `data/celebrity/`; `data/fomc/scheduler.py` via the `fomc-sched` thread).
> **Not built yet:** the long-lived `scraper` service (Playwright/PRAW) —
> `data/scrapers/` doesn't exist, so only `social_posts` stays empty (Twitter/Reddit
> scrapers are still planned). The `ml_worker` runs but has no trained model pickles
> or Gemma endpoint yet.

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

### Data Flow: Realtime Market Data (During Market Hours)

```
FastAPI lifespan (startup)
    └─ _SupervisorWatchdog (daemon thread)
           └─ subprocess: supervisor.py
                  │
                  ├─ IBKR service (ibkr_service.py)
                  │    • 50 core ETFs/stocks via keepUpToDate 1-min bars
                  │    • 3-layer zombie detection:
                  │      Layer 0: error codes 1100/1101/1102/2108 (instant)
                  │      Layer 1: reqCurrentTime() heartbeat every 30s (3 strikes → reconnect)
                  │      Layer 2: global last_bar_at timeout 120s (catch-all)
                  │    • On 1101 (data lost): resubscribe all streams without full reconnect
                  │    • Exponential backoff: 10s → 20s → 300s max (resets after 5min stable)
                  │    • Feeds CrossValidator with every bar's close price
                  │
                  ├─ Finnhub WS service (finnhub_ws.py)
                  │    • Same 50 symbols via wss://ws.finnhub.io (real-time trade ticks)
                  │    • _BarAccumulator: ticks → 1-min OHLCV bars in memory
                  │    • Flush completed bars to market_data_1min every 5s (source='finnhub')
                  │    • ON CONFLICT: IBKR rows preserved over Finnhub (IBKR is higher fidelity)
                  │    • Feeds CrossValidator with every tick's price
                  │
                  ├─ CrossValidator (shared instance)
                  │    • Every 30s: compare IBKR vs Finnhub prices per symbol
                  │    • IBKR stale >120s but Finnhub live → WARNING (IBKR may be zombie)
                  │    • Finnhub stale >120s but IBKR live → WARNING (Finnhub may be zombie)
                  │    • Price divergence >2% → ERROR (data integrity issue)
                  │
                  ├─ Massive poller (massive_poller.py)
                  │    • Remaining ~3000 symbols not covered by IBKR/Finnhub
                  │    • Every 60s with random jitter (0-18s per symbol)
                  │    • ~15 min delayed (Massive Starter plan)
                  │    • Error classification: 429/5xx → retryable, consecutive failure tracking
                  │
                  └─ Close 30m refresher (close_30min.py)
                       • 16:05 + 20:05 ET: refresh bars_30m from Massive (Yahoo fallback)

Supervisor watchdog:
    • Monitors all child tasks via asyncio.wait(FIRST_COMPLETED)
    • Crashed task → exponential backoff restart (2s → 4s → ... → 300s)
    • Health reporter prints HEALTH:{json} to stdout every 30s
    • FastAPI _SupervisorWatchdog thread reads stdout, auto-restarts subprocess
    • /health endpoint reports "degraded" if supervisor is dead
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

### 实时数据流（开盘时间）

```
FastAPI 启动
    └─ _SupervisorWatchdog（守护线程）
           └─ 子进程: supervisor.py
                  │
                  ├─ IBKR 服务：50 个核心标的，亚秒级 1 分钟 K 线
                  │    三层僵尸检测：
                  │    ① 错误码 1100/1101/1102/2108（即时）
                  │    ② reqCurrentTime() 心跳 30s（连续 3 次失败 → 重连）
                  │    ③ 全局数据新鲜度 120s（兜底）
                  │
                  ├─ Finnhub WS 服务：同 50 标的，实时 trade tick → 1 分钟 bar
                  │    ON CONFLICT: IBKR 行优先保留
                  │
                  ├─ CrossValidator（共享实例）
                  │    每 30s 比较两边价格：
                  │    一方停滞 >120s → 警告（可能 zombie）
                  │    价格偏差 >2% → 错误（数据完整性问题）
                  │
                  ├─ Massive 轮询：剩余 ~3000 标的，60s 间隔，~15 分延迟
                  │
                  └─ 收盘 30 分钟刷新：16:05 + 20:05 ET
```

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
