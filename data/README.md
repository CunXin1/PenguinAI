# Data Layer — Ingestion & Scrapers

## English

### Overview

The data layer handles all external data acquisition for PenguinAI. It is split into two categories:

- **Ingestion** (`data/ingestion/`): Structured market data — price bars from IBKR and Polygon.io
- **Scrapers** (`data/scrapers/`): Unstructured alternative data — social media, SEC filings, FOMC documents

The scraper runner is a lightweight long-lived process that dispatches Celery tasks on a schedule. It does **not** run FinBERT scoring inline — it delegates that to the ML Celery worker to avoid loading GPU models in this container.

### Structure

```
data/
├── ingestion/
│   ├── ibkr_stream.py          Real-time 1-min bar stream via ib_insync WebSocket
│   ├── polygon_loader.py       Bulk historical bar download from Polygon.io REST API
│   └── historical_bootstrap.py One-time script to import user's existing 30-min dataset
├── scrapers/
│   ├── runner.py               Long-lived scheduler process (dispatches Celery tasks)
│   ├── twitter_scraper.py      Playwright-based scraper for VIP finance accounts
│   ├── reddit_scraper.py       PRAW scraper for r/wallstreetbets, r/stocks
│   └── sec_scraper.py          SEC EDGAR: 13F filings + FOMC statements
├── Dockerfile
└── __init__.py
```

### Data Sources

#### IBKR WebSocket (`ibkr_stream.py`)
- **What**: Real-time 1-minute bar stream during market hours (9:30am–4pm ET)
- **How**: `ib_insync` subscribes to `reqRealTimeBars` (5-second resolution, aggregated to 1-min)
- **Writes to**: `market_data_1min` table
- **Historical limit**: ~6 months via `reqHistoricalData`
- **Requires**: TWS or IB Gateway running locally on port 7497

```python
from data.ingestion.ibkr_stream import IBKRStream

stream = IBKRStream(host="127.0.0.1", port=7497, client_id=1)
await stream.connect()
await stream.run_forever(tickers=["NVDA", "AAPL"], db_writer=your_write_fn)
```

#### Polygon.io (`polygon_loader.py`)
- **What**: Historical bars — minute, 30-minute, daily
- **Coverage**: 2003–present for most US stocks
- **Pagination**: Auto-handled via `next_url` cursor
- **Rate limit**: 200ms sleep between requests; 429 → 12-second backoff
- **Writes to**: `market_data_30min` or `market_data_daily`

```python
from data.ingestion.polygon_loader import PolygonLoader
from datetime import date

loader = PolygonLoader(api_key="YOUR_KEY")
await loader.bulk_load_tickers(
    tickers=["NVDA", "AAPL"],
    from_date=date(2020, 1, 1),
    to_date=date.today(),
    timespan="minute",
    multiplier=30,
    db_writer=your_write_fn,
)
await loader.close()
```

#### Twitter/X Scraper (`twitter_scraper.py`)
- **What**: Recent tweets from curated VIP finance accounts
- **How**: Playwright browser automation (no official API needed)
- **Extracts**: Cashtag mentions (`$NVDA`), content, author
- **Adds to**: `social_posts` table after FinBERT scoring in ML worker
- **VIP list**: Configured in `VIP_ACCOUNTS` list in `twitter_scraper.py`

To add new accounts, append to `VIP_ACCOUNTS`:
```python
VIP_ACCOUNTS = [
    "jimcramer",
    "CathieDWood",
    "your_new_account",  # ← add here
]
```

#### Reddit Scraper (`reddit_scraper.py`)
- **What**: Hot and new posts from finance subreddits
- **Subreddits**: `wallstreetbets`, `stocks`, `investing`, `StockMarket`
- **Extracts**: Ticker mentions (uppercase words, filtered against blacklist)
- **Requires**: PRAW credentials in `.env`

#### SEC EDGAR (`sec_scraper.py`)
- **13F Filings**: Quarterly holdings for tracked celebrities (Buffett, Cathie Wood, etc.)
- **FOMC Statements**: Fed Reserve statement text → hawk/dove NLP scoring
- **API**: Public EDGAR JSON API, no auth required (User-Agent header required)

To add a new celebrity to track, add their SEC CIK to `CELEBRITY_CIKS`:
```python
CELEBRITY_CIKS = {
    "berkshire_hathaway": "0001067983",
    "ark_invest":         "0001579982",
    "new_fund":           "0001234567",  # ← add CIK here
}
```

### Scraper Runner (`runner.py`)

The runner is a lightweight process that runs as its own Docker service. It:
1. Dispatches `scrape_social_media` Celery task every 30 minutes
2. Fetches and stores FOMC statements every 6 hours
3. Handles `SIGTERM` gracefully for clean Docker shutdown
4. Logs all activity with timestamps

```bash
# Run locally
python -m data.scrapers.runner

# Or via Docker
docker-compose up scraper
```

### Importing Your Existing 30-Min Dataset

If you have historical 30-min bar data (CSV/Parquet), use `historical_bootstrap.py`:

```bash
# The import script will be written when you share your data format tomorrow
python scripts/bootstrap_universe.py   # first, populate tickers table
python data/ingestion/historical_bootstrap.py --path /your/data/path
```

---

## 中文

### 模块概述

数据层负责 PenguinAI 所有外部数据的获取，分为两类：
- **结构化行情数据**（`data/ingestion/`）：来自 IBKR 实时流和 Polygon.io 历史接口的价量数据
- **非结构化替代数据**（`data/scrapers/`）：社交媒体、SEC 13F 持仓、美联储声明

爬虫 runner 是轻量级长驻进程，通过派发 Celery 任务来触发实际工作。**FinBERT 打分不在此容器内运行**，而是委托给 ML worker，避免在爬虫容器中加载 GPU 模型。

### 数据源说明

| 数据源 | 内容 | 写入表 | 频率 |
|--------|------|--------|------|
| IBKR WebSocket | 实时1分钟K线 | `market_data_1min` | 盘中实时 |
| Polygon.io | 历史30分钟/日线 | `market_data_30min`, `market_data_daily` | 按需拉取 |
| Twitter/X | 财经大V推文 | `social_posts` | 每30分钟 |
| Reddit WSB | 财经板块帖子 | `social_posts` | 每30分钟 |
| SEC EDGAR | 13F持仓+FOMC声明 | `celebrity_holdings`, `fomc_statements` | 每季度/每次会议 |

### 新增推特追踪账号

在 `data/scrapers/twitter_scraper.py` 的 `VIP_ACCOUNTS` 列表中添加账号名称（不含@符号）：
```python
VIP_ACCOUNTS = [
    "jimcramer",
    "CathieDWood",
    "your_new_vip_account",  # 在此添加
]
```

### 导入已有历史数据

明天导入你的 30 分钟历史数据时，提供数据文件格式（CSV/Parquet/数据库导出），我来写对应的导入脚本。
