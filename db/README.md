# Database — TimescaleDB Schema & Migrations

## English

### Overview

PenguinAI uses **TimescaleDB** (PostgreSQL 16 with the TimescaleDB extension) as the primary data store. The schema is split into two categories:

- **Time-series tables** (Hypertables): Market data, indicators, social posts — partitioned by time automatically
- **Relational tables**: Users, tickers, watchlists, signal cache, fundamentals

**pgvector** extension is enabled for RAG embedding storage and cosine similarity search on `social_posts`.

### Schema Files

```
db/
├── schema/
│   ├── 01_extensions.sql      Enable timescaledb, vector, uuid-ossp
│   ├── 02_timeseries.sql      Real model: instruments + bars_30m + bars_1d (indicators
│   │                          inline) + import bookkeeping; market_data_1min; social/news/fomc
│   ├── 03_relational.sql      Regular tables (users, tickers, watchlists, signal_cache, etc.)
│   └── 04_compat_views.sql    Views market_data_30min / market_data_daily / indicators_30min
│                              (+ v_bars_30m / v_bars_1d) over the real model
├── market_data/              Parquet → TimescaleDB loader (import_features_to_timescale.py)
└── migrations/
    ├── env.py                 Alembic async migration environment
    ├── script.py.mako         Migration file template
    └── versions/              Generated migration files (git-tracked)
```

> **Data model note.** The real market data lives in `instruments` / `bars_30m` /
> `bars_1d` (loaded from `data/30min_data` + `data/daily_data` parquet via
> `make import-30min`). The app/ML query the familiar `market_data_30min`,
> `market_data_daily`, `indicators_30min` names, which are now **compatibility
> views** (`04_compat_views.sql`) over that model — prices are the adjusted
> (`adj_*`) series and `indicators_30min` exposes model-ready features matching
> `ml/models/xgboost_trainer.FEATURE_COLS`. `market_data_1min` stays a real table
> (IBKR + Massive minute streams).

### Tables Reference

#### Time-Series Tables (Hypertables)

| Table | Partition | Primary Index | Size Estimate |
|-------|-----------|---------------|---------------|
| `bars_30m` | ts (1 mo) | (instrument_id, ts DESC) | ~236M rows — PRIMARY 30-min store + inline indicators |
| `bars_1d` | ts (1 yr) | (instrument_id, ts DESC) | ~19M rows — daily bars + indicators + returns |
| `market_data_1min` | time | (ticker, time DESC) | Growing from today (IBKR + Massive) |
| `social_posts` | time | (ticker, time DESC) + ivfflat vector | Grows with scraping |
| `news_articles` | time | (ticker, time DESC) | Grows with scraping |
| `fomc_statements` | time | — | < 1000 rows |

`instruments` (symbol ↔ instrument_id) is the dimension; `import_runs` /
`import_files` / `dataset_metadata` are load bookkeeping.

#### Compatibility Views (app/ML names → real model)

| View | Backed by | Exposes |
|------|-----------|---------|
| `market_data_30min` | `bars_30m` ⋈ `instruments` | time, ticker, OHLCV (adjusted), vwap |
| `market_data_daily` | `bars_1d` ⋈ `instruments` | time, ticker, OHLCV, adjusted_close |
| `indicators_30min` | `bars_30m` ⋈ `instruments` | time, ticker, FEATURE_COLS (incl. derived scale-free feats) |
| `v_bars_30m` / `v_bars_1d` | `bars_*` ⋈ `instruments` | symbol, asset_type, et_time, all columns |

#### Relational Tables

| Table | Primary Key | Description |
|-------|-------------|-------------|
| `users` | UUID | Auth + tier (FREE/PRO/PREMIUM/ADMIN) |
| `tickers` | ticker TEXT | Stock universe (~2000 rows) |
| `watchlists` | (user_id, ticker) | User → ticker many-to-many |
| `signal_cache` | ticker TEXT | Latest computed signal per ticker |
| `celebrity_holdings` | UUID | 13F + daily disclosure filings |
| `earnings` | (ticker, report_date) | EPS actual/estimate/surprise |
| `fundamentals` | (ticker, date) | PE ratio, market cap daily snapshot |
| `ml_models` | UUID | Model version registry |

### signal_cache — The Core Contract

The `signal_cache` table is the interface between the ML layer and the API layer. Its schema is the **single source of truth** for the signal output contract.

```sql
-- Key columns
ticker         TEXT PRIMARY KEY   -- e.g. 'NVDA'
direction      TEXT               -- 'LONG' | 'SHORT' | 'NEUTRAL'
confidence     NUMERIC(5,4)       -- 0.0 – 1.0
holding_period TEXT               -- 'INTRADAY' | 'SHORT_TERM' | 'SWING' | 'POSITION'
xgb_prob_up    NUMERIC(5,4)       -- XGBoost probability
rf_prob_up     NUMERIC(5,4)       -- RF probability
ensemble_prob  NUMERIC(5,4)       -- Weighted ensemble
finbert_score  NUMERIC(5,4)       -- FinBERT sentiment [-1, 1]
ai_attribution TEXT               -- ≤150 chars
ai_analysis    TEXT               -- ≤300 chars
tier_required  TEXT               -- 'FREE' | 'PRO' | 'PREMIUM'
computed_at    TIMESTAMPTZ
expires_at     TIMESTAMPTZ        -- Top-100: +1h, cold: +4h
```

**If you change this table, you must also update:**
1. `backend/app/models/signal_cache.py` (SQLAlchemy ORM)
2. `backend/app/schemas/signal.py` (Pydantic response schema)
3. `frontend/src/lib/types.ts` (TypeScript types)
4. `ml/tasks/hourly_signal_cache.py:_upsert_signal()` (SQL insert)

### Initial Setup

The schema files in `db/schema/` are automatically executed by Docker when TimescaleDB first initializes (via the `docker-entrypoint-initdb.d` volume mount). For manual setup:

```bash
# Via docker-compose (automatic on first run)
docker-compose up timescaledb

# Or manually connect and run scripts
psql -U penguinai -d penguinai -f db/schema/01_extensions.sql
psql -U penguinai -d penguinai -f db/schema/02_timeseries.sql
psql -U penguinai -d penguinai -f db/schema/03_relational.sql

# Or via Makefile shortcut
make db-init
```

### Alembic Migrations

Alembic manages schema changes **after** initial creation. The `env.py` imports all SQLAlchemy ORM models so it can auto-detect changes.

```bash
cd backend

# Generate a migration from ORM model changes
alembic revision --autogenerate -m "add user_preferences table"

# Apply all pending migrations
alembic upgrade head

# Check current revision
alembic current

# Rollback one step
alembic downgrade -1

# View migration history
alembic history --verbose
```

**Important**: TimescaleDB hypertable operations (like creating a new hypertable or adding columns to one) may need manual SQL in the migration file, as Alembic doesn't know about TimescaleDB-specific commands.

### Useful Queries

```sql
-- Check TimescaleDB table sizes
SELECT hypertable_name, pg_size_pretty(hypertable_size(hypertable_name::regclass))
FROM timescaledb_information.hypertables;

-- Count bars per ticker (sanity check after import)
SELECT ticker, count(*), min(time), max(time)
FROM market_data_30min
GROUP BY ticker
ORDER BY count DESC
LIMIT 20;

-- Check signal cache freshness
SELECT ticker, direction, confidence, computed_at, expires_at
FROM signal_cache
WHERE expires_at > now()
ORDER BY confidence DESC
LIMIT 10;

-- Find tickers with missing data (gap detection)
SELECT ticker, count(*) as bar_count
FROM market_data_30min
WHERE time >= '2024-01-01'
GROUP BY ticker
HAVING count(*) < 1000
ORDER BY bar_count;
```

### pgvector for RAG

The `social_posts.embedding` column stores 384-dimensional vectors (MiniLM-L6). Cosine similarity search uses the IVFFlat index:

```sql
-- Semantic search for ticker-specific posts (used by RAG retriever)
SELECT content, 1 - (embedding <=> '[0.1, 0.2, ...]'::vector) AS similarity
FROM social_posts
WHERE ticker = 'NVDA'
  AND time >= now() - INTERVAL '72 hours'
ORDER BY embedding <=> '[0.1, 0.2, ...]'::vector
LIMIT 5;
```

---

## 中文

### 模块概述

PenguinAI 使用 **TimescaleDB**（PostgreSQL 16 + TimescaleDB 扩展）作为主数据库，同时启用 **pgvector** 扩展用于 RAG 向量检索。

### 表分类

| 分类 | 表名 | 说明 |
|------|------|------|
| 时序（Hypertable） | `market_data_30min` | 历史30分钟K线，~1.7亿行 |
| 时序（Hypertable） | `market_data_1min` | 实时1分钟K线，从今天开始累积 |
| 时序（Hypertable） | `indicators_30min` | 技术指标，与K线对齐 |
| 时序（Hypertable） | `social_posts` | 社媒帖子 + FinBERT分数 + pgvector向量 |
| 关系表 | `signal_cache` | 信号缓存，ML层和API层的契约边界 |
| 关系表 | `users` | 用户信息和分层 |
| 关系表 | `tickers` | 股票池（约2000条） |
| 关系表 | `watchlists` | 用户自选股 |
| 关系表 | `celebrity_holdings` | 名人持仓（13F + 日内披露） |

### signal_cache 变更规则

修改 `signal_cache` 表结构时，必须同步修改以下四个位置：
1. `db/schema/03_relational.sql`（原始建表 SQL）
2. `backend/app/models/signal_cache.py`（SQLAlchemy ORM）
3. `backend/app/schemas/signal.py`（Pydantic Schema）
4. `frontend/src/lib/types.ts`（TypeScript 类型）
5. `ml/tasks/hourly_signal_cache.py:_upsert_signal()`（插入 SQL）

漏改任何一处都会导致 API 返回错误或前端类型不匹配。

### Alembic 迁移流程

```bash
cd backend
# 生成迁移文件（基于 ORM 模型变化自动检测）
alembic revision --autogenerate -m "添加新表描述"

# 应用所有待处理迁移
alembic upgrade head

# 回滚一步
alembic downgrade -1
```

注意：TimescaleDB 专有操作（如创建 Hypertable、添加 Hypertable 列）需要在迁移文件中手动编写 SQL，Alembic 无法自动生成这些语句。
