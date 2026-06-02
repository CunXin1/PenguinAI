# Data Sources Guide

## English

### Overview

PenguinAI ingests data from five categories of sources. Each source feeds a specific table in TimescaleDB and serves a distinct role in the signal generation pipeline.

### Source Matrix

| Source | Category | Tables Fed | Frequency | Required |
|--------|----------|-----------|-----------|----------|
| User's existing dataset | Historical bars | `market_data_30min` | One-time import | ✅ Yes |
| IBKR WebSocket | Real-time bars | `market_data_1min` | Continuous (market hours) | ✅ Yes |
| Polygon.io | Supplemental bars | `market_data_30min`, `market_data_daily` | On-demand / backfill | ⚡ Recommended |
| Twitter/X (Playwright) | Social sentiment | `social_posts` | Every 30 min | ⚡ Recommended |
| Reddit PRAW | Social sentiment | `social_posts` | Every 30 min | ⚡ Recommended |
| SEC EDGAR | Smart money | `celebrity_holdings`, `fomc_statements` | Quarterly / per meeting | 📋 Optional for MVP |

### 1. User's Existing 30-Min Dataset

**What it is**: Full-market 30-min OHLCV bars (adjusted + unadjusted) from 2000 to present, covering ~2000 US stocks and ETFs.

**Size estimate**: ~170M rows, ~10 GB compressed in TimescaleDB.

**Import**: Custom import script will be written based on your data format (CSV/Parquet/database).

**Columns expected**:
```
time (TIMESTAMPTZ), ticker (TEXT),
open, high, low, close (NUMERIC),
volume (BIGINT), vwap (NUMERIC, optional),
adjusted (BOOLEAN)
```

### 2. IBKR Real-Time Stream

**File**: `data/ingestion/ibkr_stream.py`

**What it provides**: Real-time 1-minute bars during market hours (9:30am–4:00pm ET). IBKR's TWS API streams 5-second bars which the `MinuteBarAggregator` class combines into 1-minute bars.

**Setup requirements**:
- IBKR TWS or IB Gateway running locally
- Port: 7497 (TWS paper) / 7496 (TWS live) / 4002 (IB Gateway)
- Market data subscription for US equities

**Historical depth via API**:
| Bar Size | Available History |
|----------|-----------------|
| 1 minute | ~6 months (practical limit) |
| 5 minutes | ~6 months–1 year |
| 30 minutes | ~5–10 years |
| Daily | 20+ years |

**Tip**: Use `reqHeadTimeStamp()` to check the exact earliest available date for each ticker.

### 3. Polygon.io

**File**: `data/ingestion/polygon_loader.py`

**Coverage**: 2003–present for most US-listed stocks.

**Plans**:
- Starter (~$79/month): Unlimited historical data, 5 API calls/minute
- Developer (~$199/month): 100 calls/minute, real-time data

**Usage example**:
```python
from data.ingestion.polygon_loader import PolygonLoader
from datetime import date

loader = PolygonLoader(api_key="YOUR_KEY")
# Download 30-min bars for a list of tickers
await loader.bulk_load_tickers(
    tickers=["NVDA", "AAPL", "MSFT"],
    from_date=date(2018, 1, 1),
    to_date=date.today(),
    timespan="minute",
    multiplier=30,
    db_writer=your_async_write_function,
)
```

**Pacing**: The loader automatically sleeps 200ms between requests and retries on 429 (rate limit) with 12-second backoff.

### 4. Twitter/X Scraper

**File**: `data/scrapers/twitter_scraper.py`

**Method**: Playwright browser automation — visits `x.com/{username}` and extracts tweets. No official API required.

**Ticker extraction**: Looks for cashtag format (`$NVDA`). Falls back to uppercase word detection.

**VIP accounts** (configured in `VIP_ACCOUNTS` list):
```python
VIP_ACCOUNTS = [
    "jimcramer",       # Jim Cramer (reverse indicator use)
    "elonmusk",        # Market-moving announcements
    "CathieDWood",     # ARK Invest positions
    "chamath",         # VC/macro commentary
]
```

**Limitations**:
- Timestamp accuracy: Playwright cannot extract exact post times without login; defaults to scrape time. Use Twitter API if precise timestamps are needed.
- Anti-bot: X.com may block headless browsers; add `user_agent` rotation and delays if needed.

### 5. Reddit PRAW

**File**: `data/scrapers/reddit_scraper.py`

**Subreddits scraped**: `wallstreetbets`, `stocks`, `investing`, `StockMarket`

**Ticker extraction**: Regex `\b([A-Z]{1,5})\b` with a blacklist of common false positives (`"DD"`, `"IPO"`, `"CEO"`, etc.).

**Setup**:
1. Create a Reddit app at `https://www.reddit.com/prefs/apps`
2. Set `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` in `.env`

**PRAW rate limits**: 60 requests/minute for OAuth apps (free). This is more than sufficient for our scraping frequency.

### 6. SEC EDGAR

**File**: `data/scrapers/sec_scraper.py`

#### 13F Filings (Quarterly Holdings)
- **What**: Institutional holdings filings submitted 45 days after each quarter end
- **Celebrities tracked**: Berkshire Hathaway (Buffett), ARK Invest (Cathie Wood)
- **API**: `https://data.sec.gov/submissions/CIK{cik}.json` — free, no auth
- **Frequency**: Quarterly (February, May, August, November)

To add a new celebrity, find their SEC CIK at `https://www.sec.gov/cgi-bin/browse-edgar` and add to `CELEBRITY_CIKS` in `sec_scraper.py`.

#### FOMC Statements
- **What**: Federal Reserve monetary policy statements
- **Scoring**: Keyword-based hawk/dove scoring — positive = hawkish, negative = dovish
- **Used as**: Global macro risk filter in `_apply_macro_filter()`
- **Frequency**: 8 FOMC meetings per year (roughly every 6 weeks)

### Data Quality Considerations

**Adjusted vs. Unadjusted Bars**
- Use `adjusted=TRUE` for ML training and signal generation (splits/dividends normalized)
- Keep `adjusted=FALSE` for backtesting with exact historical prices

**Bar Alignment**
- `market_data_30min` and `indicators_30min` must be time-aligned (same timestamps)
- Run `scripts/backfill_indicators.py` after importing new bar data

**Gap Detection**
```sql
-- Find tickers with suspiciously low bar counts (potential data gaps)
SELECT ticker, count(*) as bars, min(time), max(time)
FROM market_data_30min
WHERE time >= '2024-01-01'
GROUP BY ticker
HAVING count(*) < 2000
ORDER BY bars;
```

---

## 中文

### 数据源汇总

| 数据源 | 类型 | 写入表 | 频率 | MVP 必要性 |
|--------|------|--------|------|-----------|
| 用户已有历史数据 | 30 分钟 K 线 | `market_data_30min` | 一次性导入 | ✅ 必须 |
| IBKR WebSocket | 实时 1 分钟 K 线 | `market_data_1min` | 盘中实时 | ✅ 必须 |
| Polygon.io | 补充历史数据 | `market_data_30min` | 按需 | ⚡ 推荐 |
| Twitter/X | 社媒情绪 | `social_posts` | 每 30 分钟 | ⚡ 推荐 |
| Reddit WSB | 社媒情绪 | `social_posts` | 每 30 分钟 | ⚡ 推荐 |
| SEC EDGAR | 机构持仓/FOMC | `celebrity_holdings`, `fomc_statements` | 每季度 | 📋 MVP 后 |

### IBKR 历史数据深度

| 粒度 | 实际可拉取历史 |
|------|--------------|
| 1 分钟 | ~6 个月 |
| 5 分钟 | ~6 个月–1 年 |
| 30 分钟 | ~5–10 年 |
| 日线 | 20+ 年 |

**结论**：IBKR 拉不到 2000 年历史数据。用户已有的 2000 年至今 30 分钟数据是核心资产，比 IBKR API 价值更高。

### 数据质量注意事项

- **分权 vs 不分权**：ML 训练和信号生成使用 `adjusted=TRUE`（分红除权标准化）；回测历史价格使用 `adjusted=FALSE`
- **Bar 对齐**：`market_data_30min` 和 `indicators_30min` 必须时间对齐。导入新 Bar 数据后需运行 `scripts/backfill_indicators.py`
- **缺口检测**：导入完成后用 SQL 检查每只股票的 Bar 数量是否合理
