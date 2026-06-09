# Data Sources Guide

## English

### Overview

PenguinAI ingests data from several source categories. Each feeds a specific
table in TimescaleDB and serves a distinct role in the signal-generation
pipeline. Some sources are **live today**; the social/smart-money sources are
**designed but not yet built** (the tables exist and stay empty until the
ingestion code lands).

### Source Matrix

| Source | Category | Tables Fed | Status | How |
|--------|----------|-----------|--------|-----|
| User's historical 30-min/daily dataset | Historical bars + indicators | `bars_30m`, `bars_1d` (+ `instruments`) | ✅ Live (236M+19.5M rows loaded) | `db/market_data/import_features_to_timescale.py` (`make import-30min`) |
| IBKR WebSocket | Real-time 1-min bars (50 core symbols) | `market_data_1min` | ✅ Live (market hours) | `data/ingestion/realtime/ibkr_service.py` |
| Finnhub WebSocket | Real-time trade ticks → 1-min bars (same 50 symbols, dual-source) | `market_data_1min` | ✅ Live (market hours) | `data/ingestion/realtime/finnhub_ws.py` |
| Massive (massive.com) — minute history | Supplemental minute bars | `data/minute_data/` parquet → `market_data_1min` | ✅ Delivered (NDX-100 + Top-20 ETF, ~2yr parquet) | `data/ingestion/massive_minute_parquet.py` (`make minute-parquet`) |
| Massive — reference + market cap | Universe metadata | `data/reference/tickers_reference.parquet`, `tickers.market_cap` | ✅ Live | `data/ingestion/massive_reference.py`, `massive_marketcap.py` |
| Massive — symbol validation | On-demand universe expansion | `symbol_requests` → `tickers` | ✅ Live (Celery, every 6h) | `ml/tasks/symbol_validation.py` |
| Finnhub — earnings calendar | EPS actual/estimate/surprise | `earnings` | ✅ Live | `data/earnings/finnhub.py` (`make fetch-earnings`) + backend lifespan scheduler |
| Twitter/X · Reddit | Social sentiment | `social_posts` | 🚧 Planned (no `data/scrapers/` yet) | designed: Playwright / PRAW |
| SEC EDGAR 13F + 13D | Smart money (Buffett, Soros, Dalio, Ackman, Trump DJT) | `celebrity_holdings` | ✅ Live | `data/celebrity/sec_13f.py` (daily auto-fetch) |
| Quiver Quant | Congressional trades (Pelosi, Tuberville, MTG, Crenshaw) | `celebrity_holdings` | ✅ Live | `data/celebrity/congress.py` (daily auto-fetch) |
| arkfunds.io | ARK Invest daily trades (Cathie Wood) | `celebrity_holdings` | ✅ Live | `data/celebrity/ark.py` (daily auto-fetch) |
| SEC EDGAR FOMC | FOMC statements | `fomc_statements` | 🚧 Planned | designed: SEC submissions API |
| Polygon.io | Supplemental bars | — | ❌ Legacy placeholder (env key only, no loader) | superseded by Massive |

> **Reality check.** `data/scrapers/` and `data/ingestion/polygon_loader.py` do
> **not** exist. The social-sentiment and FOMC tables are created by the schema
> but are not populated yet — those pipeline steps degrade gracefully.
> Celebrity holdings **is live** (see `docs/celebrity-holdings.md`).

---

### 1. Historical 30-Min / Daily Dataset (the core asset)

**What it is**: Full-market 30-min OHLCV bars + inline technical indicators,
2000–present, plus a daily roll-up with multi-horizon returns. This is the
user's own dataset, cleaned and normalized through a dedicated pipeline.

**Coverage** (as of the 2026-06 load): **4,167 common stocks + 2,133 ETFs =
6,300 symbols** (preferred shares, SPAC units, baby bonds, warrants, and delisted
tickers removed). Adjusted series are continuous 2000→present.

**Where it lands**:
- `instruments` — symbol ↔ `instrument_id` dimension
- `bars_30m` — **~236M rows**, 30-min bars with `raw_*` + `adj_*` prices and inline indicators (PRIMARY training source)
- `bars_1d` — **~19.5M rows**, daily bars + indicators + returns (`ret_1d … ret_252d`, `gap_overnight`)

The app/ML keep querying the familiar names `market_data_30min`,
`market_data_daily`, and `indicators_30min` — these are **compatibility views**
over `bars_30m` / `bars_1d` (see `db/schema/04_compat_views.sql`). Prices in the
views are the adjusted (`adj_*`) series.

**Import**:
```bash
make db-init        # apply db/schema/*.sql
make import-30min   # db/market_data/import_features_to_timescale.py: per-symbol
                    # parquet (data/30min_data, data/daily_data) → bars_30m / bars_1d
                    # via COPY + index drop/rebuild
```

**Cleaning / build pipeline** lives in `backend/scripts/market_data/`
(`ibkr_fetch.py`, `yahoo_fetch.py`, `compute_indicators.py`,
`filter_common_stock.py`, `prune_delisted.py`, `fill_adj_gap.py`, …). The full
data dictionary, indicator formulas, and reproduce-from-scratch steps are
documented in **`data/docs/`** (start at `data/docs/README.md`).

**Train/serve parity**: training reads the `data/30min_data` parquet via DuckDB;
serving reads the `indicators_30min` view. Both derive features through the same
SQL, so there is no train/serve skew.

### 2. IBKR Real-Time Stream

**File**: `data/ingestion/realtime/ibkr_service.py` (managed by supervisor)

**What it provides**: Real-time 1-minute bars during market hours via
`reqHistoricalDataAsync(keepUpToDate=True)`, written to `market_data_1min` with
`source='ibkr'`. 50 symbols (10 ETFs + 40 stocks by 60-day ADDV). Idempotent
upsert on `(ticker, time)`.

**Zombie prevention** (3-layer):
1. **Error codes** (instant): `errorEvent` handler catches 1100 (connectivity
   lost), 1101 (restored, data lost → resubscribe all), 1102 (restored, data
   maintained), 2108 (data farm inactive → force reconnect).
2. **Heartbeat** (every 30s): `reqCurrentTime()` with 10s timeout. 3 consecutive
   failures → force reconnect. Detects silent TCP death.
3. **Data freshness** (every 1s): if no bar from any symbol for 120s → force
   reconnect. Catch-all for edge cases layers 1-2 miss.

**Reconnection**: exponential backoff 10s → 20s → ... → 300s max. Backoff only
resets after 5 minutes of sustained data flow (prevents thrashing on flaky
connections). `ib.RequestTimeout = 30` prevents blocking calls from hanging
indefinitely.

**Setup requirements**:
- IBKR TWS or IB Gateway running locally
- `IBKR_HOST` / `IBKR_PORT` / `IBKR_CLIENT_ID` in `.env`
  (7497/7496 TWS paper/live · 4002/4001 IB Gateway paper/live)
- Market-data subscription for US equities

### 2b. Finnhub WebSocket (Dual-Source Hot Standby)

**File**: `data/ingestion/realtime/finnhub_ws.py` (managed by supervisor)

**What it provides**: Real-time trade ticks from Finnhub's US SIP feed
(~150ms latency), aggregated into 1-minute OHLCV bars in memory, then flushed
to `market_data_1min` with `source='finnhub'` every 5 seconds.

**Why both IBKR and Finnhub?** Neither source is a "fallback" — both run
concurrently and write to the same table. The `ON CONFLICT` upsert preserves
IBKR rows (higher fidelity: direct exchange data, accurate volume) over Finnhub
rows. If IBKR goes zombie, Finnhub bars fill the gap automatically with no
switching logic needed.

**CrossValidator** (shared between IBKR and Finnhub):
- Every 30s, compares latest prices from both feeds per symbol.
- If one source's price stops advancing for >120s while the other is live →
  WARNING log (potential zombie on the stale side).
- If both sources have fresh prices but they diverge >2% → ERROR log (data
  integrity issue, possible bad feed or corporate action mid-stream).

**Tick → Bar aggregation** (`_BarAccumulator`):
- Each trade tick updates the in-progress bar for the current minute: open (first
  tick), high/low (running max/min), close (latest tick), volume (cumulative).
- Completed bars (whose minute is strictly in the past) are flushed to DB.
- Finnhub tick data may be sparser than IBKR (not every trade is captured), so
  volume from Finnhub is typically lower — the upsert uses
  `GREATEST(market_data_1min.volume, EXCLUDED.volume)` to preserve the higher
  volume.

**Finnhub free tier limits**: 50 WebSocket symbols (matches our IBKR set), 1
connection per API key, 60 REST calls/min, real-time US SIP data only (non-US is
delayed/EOD).

**Config**: `FINNHUB_API_KEY` in `.env`, `FINNHUB_WS_ENABLED=true` (default).
Requires `websockets>=13.0` package.

### 3. Massive (massive.com)

The **$29 Starter** plan gives minute history (15-min delayed) over a
Polygon-compatible API. Massive is used three ways:

**a) Minute-bar history** — `data/ingestion/massive_minute_parquet.py`
(`make minute-parquet`)
- Pulls minute bars for the Nasdaq-100 + Top-20 ETFs (~2yr) → `data/minute_data/`
  parquet (self-contained; schema matches `ibkr_fetch` BASE_SCHEMA). Resumable
  (skips files that already exist).

**b) Universe reference + market cap** — `massive_reference.py`,
`massive_marketcap.py`
- Reference dump → `data/reference/tickers_reference.parquet` (symbol → name,
  type, exchange, active flag).
- Market caps backfilled into `tickers.market_cap` (drives the heatmap sizing).

**c) Symbol validation** — `ml/tasks/symbol_validation.py` (Celery, every 6h)
- When a user searches a symbol we don't cover, it lands in `symbol_requests`.
  This job classifies each against Massive's reference API: real-but-uningested,
  delisted, or junk/typo. No user free text reaches any LLM — only the relational
  DB is touched.

**Config**: `MASSIVE_API_KEY`, `MASSIVE_BASE_URL` in `.env`.

### 4. Finnhub — Earnings Calendar

**Files**: `data/earnings/finnhub.py` (loader) · `data/earnings/scheduler.py`
(scheduler) · **run**: `make fetch-earnings`

**What it provides**: Forward earnings calendar + EPS actual/estimate/surprise +
report session (`bmo`/`amc`) → the `earnings` table. Idempotent: re-run to
backfill actuals once results publish.

**Scheduled**: Backend lifespan (not Celery Beat) — fetches on startup, then
2×/weekday at 08:00 ET (pre-market) and 18:00 ET (post-market). The scheduler
also ensures 50 core stocks exist in the `tickers` table before each fetch (FK
requirement). Celery task `fetch_earnings` remains available for manual invocation.

**Config**: `FINNHUB_API_KEY` in `.env`. Powers the `/api/earnings/*` endpoints
and the frontend Earnings page. See **`docs/earnings.md`** for full details.

### 5. Social Sentiment — Twitter/X + Reddit *(planned, not built)*

**Intended files**: `data/scrapers/twitter_scraper.py` (Playwright),
`data/scrapers/reddit_scraper.py` (PRAW) → `social_posts`.

The `social_posts` table (FinBERT score + pgvector embedding) and the Celery
`scrape_social_media` task **exist as stubs**, but the scraper modules and the
`data/scrapers/` directory have **not been created yet**. Until then,
`social_posts` is empty and the sentiment/RAG steps return neutral/empty.

Planned design:
- Twitter: cashtag (`$NVDA`) extraction from a curated VIP-account list.
- Reddit: `wallstreetbets` / `stocks` / `investing` / `StockMarket`, with a
  false-positive blacklist (`DD`, `IPO`, `CEO`, …).
- Reddit creds: `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT`.

### 6. Celebrity Holdings — SEC EDGAR + Quiver Quant + ARK *(live)*

Three free data sources populate `celebrity_holdings` daily. See
**`docs/celebrity-holdings.md`** for full details.

**Files**: `data/celebrity/sec_13f.py`, `data/celebrity/congress.py`,
`data/celebrity/ark.py`

**Auto-update**: Backend lifespan fetches on startup + daily at 19:00 ET
(weekdays). No Celery Beat dependency.

**CLI**: `make fetch-celebrities` (runs all three).

### 6b. FOMC Statements *(planned, not built)*

**Intended**: `data/scrapers/sec_scraper.py` → `fomc_statements` with
keyword-based hawk/dove scoring, consumed by
`signal_engine._apply_macro_filter()`. The FOMC filter no-ops when the
table is empty.

### 7. News *(live)*

**Files**: `data/news/ingest.py` (fetch + FinBERT score + store) · `data/news/scheduler.py`
(lifespan thread) · `data/news/constants.py` (tier definitions)

**Source priority**: Massive API (paid, primary) → Google News RSS (free, secondary)
→ Finnhub REST (free tier, last resort — save quota for earnings/realtime).

**Storage**: `news_articles` hypertable — one row per (article, ticker). Same article
can have different `finbert_score` for different tickers (e.g. "Intel surges on
Google order" is negative for NVDA, positive for INTC). FinBERT prepends the ticker
to the headline before scoring.

**Schedule**: Backend lifespan thread — full ingest on startup, then tier-1 (MAG7 +
top ETFs, 12 tickers) every 15 min, tier-2 (remaining ~81 hot tickers) every 60 min.
Cold tickers are fetched on-demand via the API, cached 10 min, not stored.

**Retention**: TimescaleDB `drop_chunks` auto-prunes at 90 days. Per-ticker limit of
20 articles per fetch to avoid bloat.

**API**: `/api/news/market` (general feed), `/api/news/hot` (DB-backed), `/api/news/{ticker}`
(hot=DB→fallback, cold=API-only). All return unified JSON with `sentiment` + `sentiment_score`.

### Data Quality Considerations

**Adjusted vs. raw bars** — `bars_30m` / `bars_1d` store both `raw_*` and `adj_*`
columns. The compat views and ML use the adjusted (`adj_*`) series; raw is kept
for exact-price backtests.

**Indicator recomputation** — indicators are computed inline during the parquet
build (`backend/scripts/market_data/compute_indicators.py`), which resets
recursive indicators (EMA/MACD/RSI/ATR/OBV/`ret_1bar`) at adjustment
discontinuities via a `_segment_id`, so a bad boundary bar cannot pollute across
eras. After importing new bars, rebuild indicators for the affected symbols.

**Gap detection**
```sql
-- Tickers with suspiciously low bar counts (potential data gaps).
-- market_data_30min is a compat view over bars_30m.
SELECT ticker, count(*) AS bars, min(time), max(time)
FROM market_data_30min
WHERE time >= '2024-01-01'
GROUP BY ticker
HAVING count(*) < 2000
ORDER BY bars;
```

---

## 中文

### 数据源汇总

| 数据源 | 类型 | 写入表 | 状态 | 入口 |
|--------|------|--------|------|------|
| 用户历史 30 分钟 / 日线数据 | 历史 K 线 + 指标 | `bars_30m`、`bars_1d`（+ `instruments`） | ✅ 已导入（2.36亿 + 1955万行） | `make import-30min` |
| IBKR WebSocket | 实时 1 分钟 K 线（50 核心标的） | `market_data_1min` | ✅ 盘中实时 | `data/ingestion/realtime/ibkr_service.py` |
| Finnhub WebSocket | 实时 trade tick → 1 分钟 bar（同 50 标的，双源互备） | `market_data_1min` | ✅ 盘中实时 | `data/ingestion/realtime/finnhub_ws.py` |
| Massive — 分钟历史 | 补充分钟 K 线 | `data/minute_data/` parquet | ✅ 已交付（NDX-100 + Top-20 ETF，~2 年） | `make minute-parquet` |
| Massive — 参考 + 市值 | 宇宙元数据 | `tickers_reference.parquet`、`tickers.market_cap` | ✅ 已接入 | `massive_reference.py` / `massive_marketcap.py` |
| Massive — 符号校验 | 按需扩展宇宙 | `symbol_requests` → `tickers` | ✅ Celery 每 6 小时 | `ml/tasks/symbol_validation.py` |
| Finnhub — 财报日历 | EPS 实际/预期/超预期 | `earnings` | ✅ 已接入 | `data/earnings/finnhub.py`（启动 + 盘前/盘后自动拉取） |
| Twitter/X · Reddit | 社媒情绪 | `social_posts` | 🚧 规划中（`data/scrapers/` 尚未创建） | Playwright / PRAW |
| SEC EDGAR 13F + 13D | 机构持仓（巴菲特、索罗斯、达里奥、阿克曼、特朗普 DJT） | `celebrity_holdings` | ✅ 已接入 | `data/celebrity/sec_13f.py` |
| Quiver Quant | 国会议员交易（佩洛西、图伯维尔等） | `celebrity_holdings` | ✅ 已接入 | `data/celebrity/congress.py` |
| arkfunds.io | ARK 每日交易（Cathie Wood） | `celebrity_holdings` | ✅ 已接入 | `data/celebrity/ark.py` |
| SEC EDGAR FOMC | FOMC 声明 | `fomc_statements` | 🚧 规划中 | SEC submissions API |
| Polygon.io | 补充 K 线 | — | ❌ 遗留占位（仅 env，无 loader） | 已被 Massive 取代 |

> **现状提醒**：`data/scrapers/` 与 `polygon_loader.py` **不存在**。社媒和 FOMC 表
> 由 schema 建好但尚未填充，相关步骤优雅降级。名人持仓 **已上线**
>（详见 `docs/celebrity-holdings.md`）。

### 核心资产：历史 30 分钟 / 日线数据

- 最终宇宙：**4,167 普通股 + 2,133 ETF = 6,300 标的**（已剔除优先股/SPAC 单位/
  baby-bond/权证/退市）。
- 已装载：`bars_30m` **约 2.36 亿行** + `bars_1d` **约 1955 万行**，均带指标。
- app/ML 仍查询 `market_data_30min` / `market_data_daily` / `indicators_30min` —
  它们现在是 `bars_30m` / `bars_1d` 上的**兼容视图**（`04_compat_views.sql`），价格
  取复权（`adj_*`）序列。
- 清洗/构建脚本在 `backend/scripts/market_data/`；完整数据字典与复现步骤见
  **`data/docs/`**（从 `data/docs/README.md` 开始）。

### 数据质量注意事项

- **复权 vs 原始**：`bars_30m` / `bars_1d` 同时存 `raw_*` 和 `adj_*`；视图和 ML 用
  `adj_*`，原始价用于精确回测。
- **指标重算**：指标在 parquet 构建期内联计算
  （`compute_indicators.py`），在复权断点用 `_segment_id` 重置递归类指标
  （EMA/MACD/RSI/ATR/OBV/`ret_1bar`），避免坏边界 bar 跨时代污染。导入新 bar 后需
  对受影响标的重算指标。
- **缺口检测**：导入后用 SQL 检查每只标的 Bar 数量是否合理（`market_data_30min` 是
  `bars_30m` 的兼容视图）。
