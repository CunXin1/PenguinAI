# Earnings Module

## English

### Overview

The Earnings module tracks quarterly EPS (Earnings Per Share) reports for the signal universe. Data is sourced from the Finnhub free-tier earnings calendar API and automatically refreshed on backend startup + twice daily (pre-market and post-market). The module powers both the frontend Earnings Calendar page and feeds into the signal engine as a fundamental data input.

### Architecture

```
data/earnings/
  __init__.py
  finnhub.py       — Finnhub API client + DB upsert (the data loader)
  scheduler.py     — Startup fetch + 2×/day scheduler + core tickers guarantee
```

```
Finnhub API ──→ data/earnings/finnhub.py ──→ earnings table (TimescaleDB)
                                                    │
                    data/earnings/scheduler.py       │
                    (startup + 08:00/18:00 ET)       │
                                                    ▼
                              backend/app/api/routes/earnings.py
                              GET /api/earnings/calendar
                              GET /api/earnings/{ticker}
                                                    │
                                                    ▼
                              frontend/src/app/earnings/page.tsx
                              (calendar view + per-ticker history)
```

### Data Source: Finnhub Free Tier

| Detail | Value |
|--------|-------|
| Endpoint | `GET /calendar/earnings?from=YYYY-MM-DD&to=YYYY-MM-DD&token=KEY` |
| Tier | Free (no paid add-ons) |
| Rate limit | ~60 requests/minute |
| Coverage | Entire US market (all symbols, one request per window) |
| Fields provided | `symbol`, `date`, `epsActual`, `epsEstimate`, `revenueActual`, `revenueEstimate`, `hour` (bmo/amc), `quarter`, `year` |
| Fields NOT provided (free tier) | `guidance_text`, `eps_surprise_pct` (computed by loader) |
| Config | `FINNHUB_API_KEY` in `.env` (free key from finnhub.io) |

### Database

**Table**: `earnings` (defined in `db/schema/03_relational.sql`)

```sql
CREATE TABLE IF NOT EXISTS earnings (
    ticker            TEXT        NOT NULL REFERENCES tickers(ticker),
    report_date       DATE        NOT NULL,
    eps_actual        NUMERIC(10, 4),
    eps_estimate      NUMERIC(10, 4),
    eps_surprise_pct  NUMERIC(8, 4),   -- computed: (actual-estimate)/|estimate|*100
    revenue_actual    BIGINT,
    revenue_estimate  BIGINT,
    guidance_text     TEXT,              -- NULL on free tier
    report_hour       TEXT,              -- 'bmo' | 'amc' (from Finnhub)
    PRIMARY KEY (ticker, report_date)
);
```

**FK constraint**: `earnings.ticker → tickers(ticker)`. The scheduler auto-inserts 50 core stocks into `tickers` before each fetch to prevent FK violations for key symbols (see Core Tickers Guarantee below).

### Ingestion Pipeline (`data/earnings/finnhub.py`)

1. **Chunking**: Large date ranges are split into ≤90-day windows (one Finnhub request each)
2. **Filtering**: Only tickers present in the `tickers` table are kept (FK requirement)
3. **Surprise %**: Computed client-side as `(actual - estimate) / |estimate| × 100` (Finnhub free tier omits this)
4. **Upsert**: `INSERT ... ON CONFLICT (ticker, report_date) DO UPDATE` — idempotent; re-runs backfill actuals as results publish
5. **Guidance preservation**: `COALESCE(EXCLUDED.guidance_text, earnings.guidance_text)` — never overwrites existing guidance with NULL
6. **Batching**: Rows upserted in batches of 500

### Core Tickers Guarantee (`data/earnings/scheduler.py`)

The scheduler maintains a `_CORE_STOCKS` dict of 50 key tickers (IBKR stream symbols + bootstrap universe). Before each earnings fetch, `ensure_core_tickers()` inserts any missing entries into `tickers` with `ON CONFLICT DO NOTHING`, ensuring:

- All IBKR-streamed stocks have earnings coverage
- Bootstrap doesn't need to have run first
- Existing ticker metadata (from bootstrap) is never overwritten

**Covered stocks**: NVDA, AAPL, MSFT, AMZN, GOOGL, GOOG, META, TSLA, AVGO, ORCL, NFLX, CRM, QCOM, AMD, MU, PLTR, ADBE, INTC, MRVL, TSM, ARM, ASML, WDC, STX, NOW, APP, CRWV, DELL, IBM, HOOD, RKLB, MSTR, NBIS, LITE, BE, IREN, GEV, LLY, UNH, ABBV, JPM, BAC, GS, V, MA, XOM, CVX, COST, WMT, HD

### Auto-Update Schedule

Managed by backend lifespan (`backend/app/main.py`), not Celery Beat:

1. **On startup**: immediately fetches (ensure core tickers + Finnhub calendar)
2. **08:00 ET weekdays**: pre-market fetch — captures BMO actuals + refreshed forward calendar
3. **18:00 ET weekdays**: post-market fetch — captures AMC actuals after market close
4. **Skips weekends**: if current time is past 18:00 Friday, targets Monday 08:00

The scheduler runs in a daemon thread (`earnings-sched`), using `asyncio.run()` for each fetch cycle. Graceful shutdown via `threading.Event` on backend stop.

Celery task remains defined in `ml/tasks/realtime_ingest.py:fetch_earnings` for manual invocation but is not in the beat schedule.

### Backend API

**Route file**: `backend/app/api/routes/earnings.py`
**Prefix**: `/api/earnings`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/calendar` | Earnings calendar for a date window (default: today−7d .. today+30d) |
| GET | `/{ticker}` | Most recent earnings history for one ticker (newest first, up to 40) |

Both endpoints are public (no auth required). Response shape:

```json
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
```

`session` ∈ `BMO` (pre-open) · `AMC` (after-close) · `TBD`.

### Frontend

**Page**: `/earnings` (`frontend/src/app/earnings/page.tsx`)
**Nav label**: "Earnings" (CalendarDays icon)

**Layout**:
1. Stat tiles (4): Upcoming / Beats / Misses / Avg Surprise
2. Tabs: Upcoming / Reported / All
3. Search bar: filter by ticker or company name
4. Calendar groups: earnings rows grouped by report date, "Today" badge
5. Expandable rows: click to show per-ticker historical detail (via `GET /earnings/{ticker}`)
6. EPS sparkline: inline SVG trend chart in expanded detail
7. Revenue display: shows actual revenue when reported, estimate otherwise
8. Guidance text: displayed in expanded detail when available

**View states**:
- `loading` — Skeleton placeholder (4 stat tiles + 3 date groups)
- `error` — Error banner with retry button
- `empty` — "No earnings data yet" with `make fetch-earnings` guidance
- `data` — Full calendar view

**Key files**:
```
frontend/src/app/earnings/page.tsx    — the page (calendar + expanded detail)
frontend/src/lib/types.ts            — EarningsEvent, EarningsSession types
frontend/src/lib/api.ts              — earnings.calendar(), earnings.byTicker()
```

### CLI Commands

```bash
make fetch-earnings                              # One-shot: today−7d .. today+30d
python -m data.earnings.finnhub                  # Same as above
python -m data.earnings.finnhub --days-back 365  # Backfill 1 year of history
python -m data.earnings.finnhub --from 2025-01-01 --to 2025-12-31  # Specific range
```

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "No earnings data yet" on frontend | `earnings` table empty | Run `make fetch-earnings` (requires `FINNHUB_API_KEY` in `.env`) |
| Earnings missing for a stock | Ticker not in `tickers` table | The scheduler auto-inserts 50 core stocks; for others, run `make bootstrap` |
| `RuntimeError: FINNHUB_API_KEY is not set` | Missing env var | Add `FINNHUB_API_KEY=your_key` to `.env` (free from finnhub.io) |
| Finnhub 429 (rate limit) | Too many requests | Free tier allows ~60 req/min; reduce `--chunk-days` for large backfills |
| EPS actuals show NULL for recent earnings | Results not yet published or fetch hasn't re-run | Wait for next scheduled fetch or run `make fetch-earnings` manually |

---

## 中文

### 概述

Earnings 模块追踪股票池中的季度 EPS（每股收益）报告。数据来自 Finnhub 免费版财报日历 API，后端启动时自动拉取，之后每个工作日盘前（08:00 ET）和盘后（18:00 ET）各拉取一次。该模块驱动前端财报日历页面，并作为基本面数据输入信号引擎。

### 文件结构

```
data/earnings/
  __init__.py
  finnhub.py       — Finnhub API 客户端 + DB upsert（数据加载器）
  scheduler.py     — 启动拉取 + 2×/天定时调度 + 核心股票保障
```

### 数据流

```
Finnhub API → finnhub.py → earnings 表 → /api/earnings/* → 前端日历页
                  ↑
            scheduler.py
       (启动 + 08:00/18:00 ET)
```

### 数据库表：`earnings`

| 列名 | 类型 | 说明 |
|------|------|------|
| `ticker` | TEXT (FK → tickers) | 股票代码 |
| `report_date` | DATE | 财报发布日期 |
| `eps_actual` | NUMERIC(10,4) | 实际 EPS（结果公布后填入） |
| `eps_estimate` | NUMERIC(10,4) | 预期 EPS |
| `eps_surprise_pct` | NUMERIC(8,4) | 超预期百分比 = (实际-预期)/|预期|×100 |
| `revenue_actual` | BIGINT | 实际营收（美元） |
| `revenue_estimate` | BIGINT | 预期营收 |
| `guidance_text` | TEXT | 前瞻指引（免费版为 NULL） |
| `report_hour` | TEXT | 'bmo'（盘前）/ 'amc'（盘后） |

主键：`(ticker, report_date)`

### 核心股票保障

调度器维护 50 只重点股票列表（IBKR 流标的 + bootstrap 宇宙）。每次拉取前自动将缺失的股票插入 `tickers` 表（`ON CONFLICT DO NOTHING`），确保：
- 所有 IBKR 流媒体股票的财报都被覆盖
- 不依赖 bootstrap 是否已运行
- 不会覆盖 bootstrap 已有的更丰富的元数据

### 自动更新机制

由后端生命周期管理（`backend/app/main.py`），不依赖 Celery Beat：

1. **启动时**：立即拉取（补全核心股票 + Finnhub 日历）
2. **工作日 08:00 ET**：盘前拉取（获取 BMO 实际值 + 更新后的日历）
3. **工作日 18:00 ET**：盘后拉取（获取 AMC 实际值）
4. **跳过周末**

### API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/earnings/calendar?from=&to=` | 日期窗口内的财报日历（默认 today−7d .. today+30d） |
| GET | `/api/earnings/{ticker}?limit=12` | 单只股票的最近财报历史（最新在前，最多 40 条） |

### 前端页面

**路由**：`/earnings`

**功能**：
- 4 个统计卡片：即将发布 / 超预期 / 不及预期 / 平均超预期率
- 3 个 Tab：即将发布 / 已报告 / 全部
- 搜索栏：按代码或公司名过滤
- 日历分组：按日期分组，"Today" 标记
- 可展开行：点击查看历史财报详情（EPS 走势图 + 营收对比 + 前瞻指引）

### CLI 命令

```bash
make fetch-earnings                              # 默认窗口（today−7d .. today+30d）
python -m data.earnings.finnhub --days-back 365  # 回填 1 年历史
```

### 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| 前端显示"无数据" | `earnings` 表为空 | 运行 `make fetch-earnings`（需 `.env` 中设置 `FINNHUB_API_KEY`） |
| 某只股票缺失 | 不在 `tickers` 表中 | 调度器自动补 50 只核心股；其他需运行 `make bootstrap` |
| EPS 实际值为空 | 结果尚未发布或尚未重新拉取 | 等待下次定时拉取或手动运行 `make fetch-earnings` |
