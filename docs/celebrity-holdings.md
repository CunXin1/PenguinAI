# Celebrity Holdings Module

## English

### Overview

The Smart Money page tracks stock transactions from institutional investors, politicians, and public figures. Data is sourced from three free APIs (no API keys required except SEC User-Agent) and automatically refreshed daily.

### Tracked Celebrities

| Celebrity | Source | Type | Data Frequency |
|-----------|--------|------|----------------|
| Warren Buffett | SEC EDGAR 13F (CIK 0001067983) | Institutional investor | Quarterly (45-day delay) |
| George Soros | SEC EDGAR 13F (CIK 0001029160) | Institutional investor | Quarterly |
| Ray Dalio | SEC EDGAR 13F (CIK 0001336528) | Institutional investor | Quarterly |
| Bill Ackman | SEC EDGAR 13F (CIK 0001649339) | Institutional investor | Quarterly |
| Cathie Wood | arkfunds.io API (ARKK/W/G/F/Q) | Fund manager | Daily |
| Nancy Pelosi | Quiver Quant API | U.S. Congress | As disclosed |
| Tommy Tuberville | Quiver Quant API | U.S. Congress | As disclosed |
| Marjorie Taylor Greene | Quiver Quant API | U.S. Congress | As disclosed |
| Dan Crenshaw | Quiver Quant API | U.S. Congress | As disclosed |
| Donald Trump | SEC EDGAR 13D/A (CIK 0000947033) | U.S. President | As filed (DJT only) |

### Data Sources

**1. SEC EDGAR 13F filings** (`data/celebrity/sec_13f.py`)
- Fetches quarterly 13F-HR filings for institutional investors
- Parses XML infotable to extract CUSIP, shares, and value
- Diffs current vs prior quarter to determine BUY/SELL/HOLD actions
- CUSIP-to-ticker mapping via static dict + fuzzy name matching
- Trump's DJT holdings fetched separately via Schedule 13D/A
- Rate limit: self-throttled to ~7 req/s (SEC allows 10)
- Requires `User-Agent` header with contact email (`SEC_USER_AGENT` in `.env`)

**2. ARK Invest daily trades** (`data/celebrity/ark.py`)
- Fetches from `arkfunds.io/api/v2/etf/trades` for 5 ETFs (ARKK, ARKW, ARKG, ARKF, ARKQ)
- Maps `direction: "Buy"/"Sell"` to BUY/SELL actions
- Aggregates shares across funds when same ticker traded in multiple ETFs on same day
- Default lookback: 30 days

**3. Congressional trades** (`data/celebrity/congress.py`)
- Fetches from Quiver Quant API (`api.quiverquant.com/beta/live/congresstrading`)
- Filters to curated `CONGRESS_CELEBRITIES` map
- Parses amount ranges (`"$1,001 - $15,000"`) to midpoint values
- Free, no API key required

### Database

**Table**: `celebrity_holdings` (defined in `db/schema/03_relational.sql`)

```sql
CREATE TABLE celebrity_holdings (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reported_at   TIMESTAMPTZ NOT NULL,
    celebrity     TEXT NOT NULL,     -- slug: 'buffett', 'pelosi', etc.
    ticker        TEXT REFERENCES tickers(ticker),
    action        TEXT NOT NULL,     -- 'BUY' | 'SELL' | 'HOLD'
    shares        BIGINT,
    value_usd     BIGINT,
    source_type   TEXT NOT NULL,     -- '13F' | 'daily_disclosure'
    filing_url    TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

**Indexes** (`db/schema/07_celebrity_unique.sql`):
- `idx_celeb_unique_trade` — unique on `(celebrity, ticker, reported_at, action)` for idempotent upserts
- `idx_celeb_celebrity` — `(celebrity, reported_at DESC)` for per-celebrity queries
- `idx_celeb_ticker` — `(ticker, reported_at DESC)` for per-ticker queries

### Backend API

**Route file**: `backend/app/api/routes/celebrity_holdings.py`
**Prefix**: `/api/celebrity-holdings`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/stats/summary` | Per-celebrity aggregates (trade count, buys, sells, latest) |
| GET | `/ticker/{ticker}` | Which celebrities traded a given ticker |
| GET | `/{celebrity}` | All trades for one celebrity |
| GET | `/` | Recent trades across all celebrities (paginated) |

All endpoints are public (no auth required). Input validation: celebrity slugs must match `[a-z_]{2,30}`, tickers match `[A-Z0-9.\-]{1,10}`.

### Auto-Update Schedule

Managed by the backend lifespan (`backend/app/main.py`), not Celery Beat:

1. **On startup**: immediately fetches all three sources in sequence (congress → ark → 13f)
2. **Daily at 19:00 ET**: sleeps until next weekday 19:00 ET, then fetches again
3. **Skips weekends**: if current time is past 19:00, targets next business day

The scheduler runs in a daemon thread (`celeb-fetch`), using `asyncio.run()` for each fetch cycle. Graceful shutdown via `threading.Event` on backend stop.

Celery tasks remain defined in `ml/tasks/realtime_ingest.py` for manual invocation (`fetch_congress_trades`, `fetch_13f_filings`, `fetch_ark_trades`) but are not in the beat schedule.

### Frontend

**Page**: `/celebrity-holdings` (`frontend/src/app/celebrity-holdings/page.tsx`)
**Nav label**: "Smart Money" (Crown icon)

**Layout**:
1. Stat tiles: Celebrities tracked / Recent buys / Recent sells
2. Celebrity cards (horizontal scroll, max 8): avatar, name, title, buy/sell counts, latest activity
3. Filter bar: Action filter (All/Buy/Sell/Hold), celebrity chip (click card to filter), search input
4. Transaction table: Ticker, Celebrity, Action badge, Shares, Value, Date — each row links to `/signals/{ticker}`

**Data flow**: `@tanstack/react-query` with mock fallback (`MOCK_CELEB_HOLDINGS`, `MOCK_CELEB_STATS`).

**Key files**:
```
frontend/src/app/celebrity-holdings/page.tsx  — the page
frontend/src/lib/celebrities.ts              — display metadata (name, title, avatar, colors)
frontend/src/lib/types.ts                    — CelebrityHolding, CelebritySummary types
frontend/src/lib/api.ts                      — celebrityHoldings API namespace
frontend/src/lib/mock.ts                     — mock data for offline rendering
```

### CLI Commands

```bash
make fetch-congress     # Congressional trades (Quiver Quant)
make fetch-13f          # SEC EDGAR 13F filings + Trump 13D
make fetch-ark          # ARK Invest daily trades
make fetch-celebrities  # All three at once
```

### Adding a New Celebrity

**Institutional investor (13F)**:
1. Find CIK at `https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK=NAME`
2. Add to `FILERS_13F` in `data/celebrity/sec_13f.py`
3. Add display metadata to `frontend/src/lib/celebrities.ts`

**Congress member**:
1. Add name → slug mapping to `CONGRESS_CELEBRITIES` in `data/celebrity/congress.py`
2. Add display metadata to `frontend/src/lib/celebrities.ts`

**Other** (custom source):
1. Create a new loader in `data/celebrity/` following the pattern of `congress.py`
2. Add to `_fetch_celebrity_holdings()` in `backend/app/main.py`
3. Add display metadata to `frontend/src/lib/celebrities.ts`

### Signal Engine Integration

The signal engine (`ml/inference/signal_engine.py:_get_celebrity_actions()`) reads from `celebrity_holdings` and passes the 3 most recent actions per ticker to the Gemma agent as "smart_money" context. This happens automatically once the table is populated — no additional wiring needed.

---

## 中文

### 概述

Smart Money 页面追踪机构投资者、国会议员和公众人物的股票交易。数据来自三个免费 API（除 SEC User-Agent 外无需 API 密钥），每日自动刷新。

### 追踪名人

| 名人 | 数据源 | 类型 | 更新频率 |
|------|--------|------|----------|
| Warren Buffett | SEC EDGAR 13F | 机构投资者 | 季度（45天延迟） |
| George Soros | SEC EDGAR 13F | 机构投资者 | 季度 |
| Ray Dalio | SEC EDGAR 13F | 机构投资者 | 季度 |
| Bill Ackman | SEC EDGAR 13F | 机构投资者 | 季度 |
| Cathie Wood | arkfunds.io API | 基金经理 | 每日 |
| Nancy Pelosi | Quiver Quant API | 美国国会 | 披露时 |
| Tommy Tuberville | Quiver Quant API | 美国国会 | 披露时 |
| Marjorie Taylor Greene | Quiver Quant API | 美国国会 | 披露时 |
| Dan Crenshaw | Quiver Quant API | 美国国会 | 披露时 |
| Donald Trump | SEC EDGAR 13D/A | 美国总统 | 提交时（仅 DJT） |

### 自动更新机制

由后端生命周期管理（`backend/app/main.py`），不依赖 Celery Beat：

1. **启动时**：立即依次采集三个数据源
2. **每日 ET 19:00**：收盘后自动采集（跳过周末）
3. **优雅退出**：后端关闭时通过 `threading.Event` 中断等待

### API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/celebrity-holdings/stats/summary` | 各名人汇总统计 |
| GET | `/api/celebrity-holdings/ticker/{ticker}` | 某 ticker 的名人交易 |
| GET | `/api/celebrity-holdings/{celebrity}` | 某名人的所有交易 |
| GET | `/api/celebrity-holdings` | 所有名人的近期交易（分页） |

### 关于 Trump 持仓

Trump 的 DJT（Trump Media & Technology Group）持仓通过 SEC EDGAR Schedule 13D/A 自动获取（114,750,000 股，41.5%）。其余 OGE 财务披露（3600+ 笔交易）仅有 PDF 格式，无免费结构化 API。如需扩展，可选：
- 付费 Quiver Quant API（$25/月）
- 用 `PublicI/pfd-parser` 解析 OGE PDF

### 添加新名人

- **机构投资者**：在 `FILERS_13F`（`data/celebrity/sec_13f.py`）添加 CIK
- **国会议员**：在 `CONGRESS_CELEBRITIES`（`data/celebrity/congress.py`）添加姓名映射
- **前端显示**：在 `frontend/src/lib/celebrities.ts` 添加元数据
