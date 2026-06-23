# Massive Data Source (Stocks Starter, $29/mo)

> Reference for what the paid Massive plan provides, what PenguinAI currently
> uses, and what is included-but-unused so we can adopt it later. No action
> required by this doc — it is an inventory.

## English

### What Massive is

Massive (massive.com) is the **rebranded Polygon.io** — the same company, same
API surface. `polygon.io/pricing` now 301-redirects to `massive.com/pricing`.
The API is therefore Polygon-compatible (`/v2/aggs`, `/v3/reference/tickers`,
`/v2/reference/news`, etc.), and any Polygon documentation applies verbatim.

We subscribe to the **Stocks "Starter" plan ($29/mo)**. Plan-level limits:

| Limit | Starter value |
|-------|---------------|
| Price | $29 / month |
| Data delay | 15 minutes (REST + delayed snapshots). Real-time is Advanced+ only |
| API call rate | Unlimited |
| History depth | 5 years |
| Coverage | All US stock tickers, 100% market coverage |
| Asset classes | US Stocks only (Options / Indices / FX / Crypto are separate plans) |

The gating model is consistent: most REST endpoints **are** on Starter but served
15-minute delayed. What is gated away from Starter is tick-level Trades & Quotes,
real-time data, WebSocket streaming, and the unified Financials product.

### What PenguinAI currently uses

Only four endpoint families are wired in today:

| Endpoint | Used for | Populates | Call sites |
|----------|----------|-----------|------------|
| `GET /v2/aggs/ticker/{t}/range/{m}/{minute\|day}/{from}/{to}` | 1m / 10m / 30m / daily bars | `bars_30m`, `bars_10m`, `bars_1d`, `market_data_1min`, parquet | `massive_minute_parquet.py`, `massive_30min_parquet.py`, `realtime/massive_poller.py`, `realtime/close_30min.py`, `realtime/warmup.py`, `realtime/ondemand.py`, `seed_market_data.py`, `services/daily_prices.py`, `scripts/backfill_1min_massive.py` |
| `GET /v2/reference/news` | Headlines + `insights` | `news_articles` | `data/news/ingest.py`, `api/routes/news.py` |
| `GET /v3/reference/tickers` (listing + `?ticker=` lookup) | name / exchange / type / active | `tickers.name`, `tickers.exchange`, `symbol_requests` | `massive_reference.py`, `ml/tasks/symbol_validation.py` |
| `GET /v3/reference/tickers/{sym}` (details) | market cap, shares, **SIC** | `tickers.market_cap`, `tickers.sector`, `tickers.industry` | `massive_marketcap.py` |

In short, we use only the "bars + reference + news" slice of Starter.

### Included in Starter but NOT yet used (adoption candidates)

All of the following are on the $29 plan (15-minute delayed), and we are not
calling them. Listed by value-to-effort.

| Capability | Endpoint | What it would enable |
|------------|----------|----------------------|
| **SIC sector / industry** — DONE | `/v3/reference/tickers/{sym}` (`sic_code`, `sic_description`) | Already captured in `massive_marketcap.py` for free (same call as market cap) → fills `tickers.sector` + `industry` for the whole universe (previously ~36 tickers had sector, `industry` was always empty). See `data/ingestion/sic_sectors.py`. Run `make fetch-marketcap`. |
| Grouped Daily | `/v2/aggs/grouped/locale/us/market/stocks/{date}` | Whole-market OHLCV for a date in ONE call — daily bulk refresh goes from N per-symbol calls to 1, and coverage extends to the entire market. |
| Full-Market Snapshot | `/v2/snapshot/locale/us/markets/stocks/tickers` | 10,000+ tickers' price / volume / day-change in one call — make the heatmap / screener change% instant instead of per-ticker SQL scans. |
| Gainers / Losers | `/v2/snapshot/locale/us/markets/stocks/{direction}` | Ready-made Top Movers feed → a new dashboard module (no such feature exists today). |
| Single-ticker / Unified Snapshot | `/v2/snapshot/.../tickers/{t}`, `/v3/snapshot` | Spot snapshot for a single or multi-ticker request. |
| Dividends | `/v3/reference/dividends` | Ex-date, amount, dividend yield → stock-page dividend stats + true dividend-adjusted prices (today adjustment is split-only). |
| Splits | `/v3/reference/splits` | Split history table → corporate-actions feature, audit price adjustment. |
| IPOs | `/vX/reference/ipos` | Upcoming + historical IPOs (2008-present) → IPO calendar feature. |
| Short Interest | `/stocks/v1/short-interest` | Bi-monthly short positions → squeeze / sentiment signal for the signal pipeline. |
| Short Volume | `/stocks/v1/short-volume` | Daily short-sale volume → same. |
| Related Companies | `/v1/related-companies/{t}` | Peer tickers → "similar stocks" on the stock page + a read-only chat-agent tool. |
| Server-side Technical Indicators | `/v1/indicators/{sma\|ema\|rsi\|macd}/{t}` | Offload TA compute. Note: we already compute these locally in pandas and they work well, so adopting this adds latency / a network dependency for little gain — low priority / likely skip. |
| Market Status / Holidays | `/v1/marketstatus/now`, `/v1/marketstatus/upcoming` | Authoritative open/closed + holiday calendar. Note: we already use the `exchange_calendars` library for this, so it is largely redundant — likely skip. |
| News `insights.sentiment` | `/v2/reference/news` (already called) | Per-ticker sentiment label we persist to `raw_metadata` but do not surface; FinBERT is our primary score, so incremental value is small. |
| Flat Files (S3 bulk) | `s3://flatfiles/...` | Bulk historical download including trades / quotes for backtesting. We already hold 2000-present parquet, so lower urgency, but it is the biggest raw-capacity item we pay for and never touch. |

### NOT on Starter (do not promise these)

| Capability | Tier required |
|------------|---------------|
| Unified Financials (income / balance / cash-flow / ratios) | Advanced + $29 add-on (not attachable to a standalone Starter plan) |
| Tick-level Trades & Quotes, Last Trade / Last Quote | Developer+ / Advanced |
| Real-time data (no 15-min delay) | Advanced+ |
| WebSocket streaming | Advanced+ |
| Forward analyst estimates | Not a Polygon/Massive product |
| Options / Indices / FX / Crypto / Economy data | Separate subscriptions |

Practical consequence: the `fundamentals` table's `pb_ratio` / `ps_ratio` /
`shares_out` columns have **no source on Starter** — financial statements are an
Advanced-tier product. `pe_ratio` is derived from the `earnings` table and
`market_cap` comes from the ticker-details endpoint, so those two are covered
without statements.

### Adoption roadmap

Agreed order, by value-to-effort. Only #1 is built; the rest are deferred.

1. SIC sector / industry — **DONE** (`data/ingestion/sic_sectors.py` + `massive_marketcap.py`).
2. Grouped Daily — bulk daily refresh in one call.
3. Full-Market Snapshot — instant heatmap / screener change%.
4. Dividends + Splits — corporate-actions data + dividend-adjusted prices.
5. Top Movers — new dashboard module from the gainers/losers snapshot.
6. Short Interest / Short Volume — new sentiment signal.
7. Related Companies — "similar stocks" + chat-agent tool.

---

## 中文

### Massive 是什么

Massive(massive.com)是 **Polygon.io 改名后的产品**——同一家公司、同一套 API。
`polygon.io/pricing` 现在 301 跳转到 `massive.com/pricing`。因此 API 与 Polygon
完全兼容(`/v2/aggs`、`/v3/reference/tickers`、`/v2/reference/news` 等),所有
Polygon 文档原样适用。

我们订阅的是 **股票 "Starter" 档($29/月)**。档位限制:

| 限制 | Starter 取值 |
|------|--------------|
| 价格 | $29 / 月 |
| 数据延迟 | 15 分钟(REST + 延迟快照)。实时仅 Advanced+ |
| 调用频率 | 无限 |
| 历史深度 | 5 年 |
| 覆盖 | 全部美股代码,100% 市场覆盖 |
| 资产类别 | 仅美股(期权 / 指数 / 外汇 / 加密为独立订阅) |

门槛逻辑一致:大多数 REST 端点 **都在** Starter 内,但延迟 15 分钟。被挡在
Starter 之外的是 tick 级 Trades & Quotes、实时数据、WebSocket 流、以及统一
Financials 产品。

### PenguinAI 现在用了哪些

当前只接入了 4 个端点家族:

| 端点 | 用途 | 写入 | 调用位置 |
|------|------|------|----------|
| `GET /v2/aggs/ticker/{t}/range/{m}/{minute\|day}/{from}/{to}` | 1m / 10m / 30m / 日线 | `bars_30m`、`bars_10m`、`bars_1d`、`market_data_1min`、parquet | `massive_minute_parquet.py`、`massive_30min_parquet.py`、`realtime/massive_poller.py`、`realtime/close_30min.py`、`realtime/warmup.py`、`realtime/ondemand.py`、`seed_market_data.py`、`services/daily_prices.py`、`scripts/backfill_1min_massive.py` |
| `GET /v2/reference/news` | 新闻 + `insights` | `news_articles` | `data/news/ingest.py`、`api/routes/news.py` |
| `GET /v3/reference/tickers`(列表 + `?ticker=` 单查) | 名称 / 交易所 / 类型 / 上市状态 | `tickers.name`、`tickers.exchange`、`symbol_requests` | `massive_reference.py`、`ml/tasks/symbol_validation.py` |
| `GET /v3/reference/tickers/{sym}`(详情) | 市值、股数、**SIC** | `tickers.market_cap`、`tickers.sector`、`tickers.industry` | `massive_marketcap.py` |

简言之,我们只用了 Starter 的 "K 线 + reference + 新闻" 这一小块。

### Starter 内含、但尚未使用(可逐步采纳)

以下能力都在 $29 档内(延迟 15 分钟),目前没有调用。按"价值÷成本"排序。

| 能力 | 端点 | 能带来什么 |
|------|------|-----------|
| **SIC 板块 / 行业** —— 已完成 | `/v3/reference/tickers/{sym}`(`sic_code`、`sic_description`) | 已在 `massive_marketcap.py` 里零成本接住(与市值同一次请求)→ 给全宇宙填 `tickers.sector` + `industry`(此前只有约 36 个票有 sector,`industry` 整列为空)。见 `data/ingestion/sic_sectors.py`。运行 `make fetch-marketcap`。 |
| Grouped Daily | `/v2/aggs/grouped/locale/us/market/stocks/{date}` | 一次调用拿某天全市场 OHLCV——日线批量刷新从 N 次逐票降为 1 次,且覆盖扩到全市场。 |
| 全市场快照 | `/v2/snapshot/locale/us/markets/stocks/tickers` | 一次拿 1 万+ 代码的价 / 量 / 当日涨跌幅——热力图 / 筛选器涨跌幅即时化,免去逐票 SQL 扫描。 |
| 涨跌幅榜 | `/v2/snapshot/locale/us/markets/stocks/{direction}` | 现成的 Top Movers 数据 → 新 Dashboard 模块(目前没有此功能)。 |
| 单票 / 统一快照 | `/v2/snapshot/.../tickers/{t}`、`/v3/snapshot` | 单票或多票即时快照。 |
| 分红 | `/v3/reference/dividends` | 除息日、金额、股息率 → 个股页股息数据 + 真·分红复权(当前复权只含拆股)。 |
| 拆股 | `/v3/reference/splits` | 拆股历史表 → 公司行为功能、校验价格复权。 |
| IPO | `/vX/reference/ipos` | 即将上市 + 历史 IPO(2008 至今)→ IPO 日历功能。 |
| 空头持仓 | `/stocks/v1/short-interest` | 双月空头持仓 → 轧空 / 情绪信号,喂给 signal pipeline。 |
| 空头成交量 | `/stocks/v1/short-volume` | 每日空头成交量 → 同上。 |
| 相似公司 | `/v1/related-companies/{t}` | 同业代码 → 个股页"相似股票" + 给 chat agent 加只读工具。 |
| 服务端技术指标 | `/v1/indicators/{sma\|ema\|rsi\|macd}/{t}` | 把 TA 计算外包。注:我们本地 pandas 已经算得很好,改用它反而引入延迟 / 网络依赖,收益不大——低优先 / 大概率不做。 |
| 市场状态 / 假日 | `/v1/marketstatus/now`、`/v1/marketstatus/upcoming` | 权威开 / 闭市 + 假日日历。注:我们已用 `exchange_calendars` 库,基本重复——大概率不做。 |
| 新闻 `insights.sentiment` | `/v2/reference/news`(已在调) | 逐票情绪标签,已落到 `raw_metadata` 但未展示;FinBERT 是主分,增量有限。 |
| Flat Files(S3 批量) | `s3://flatfiles/...` | 批量历史下载,含 trades / quotes,适合回测。我们已有 2000 至今 parquet,紧迫性低,但这是付费却完全没碰的最大原始产能项。 |

### 不在 Starter 内(别指望)

| 能力 | 所需档位 |
|------|----------|
| 统一 Financials(利润表 / 资产负债 / 现金流 / ratios) | Advanced + $29 add-on(无法挂在单独 Starter 上) |
| tick 级 Trades & Quotes、Last Trade / Last Quote | Developer+ / Advanced |
| 实时数据(无 15 分钟延迟) | Advanced+ |
| WebSocket 流 | Advanced+ |
| 前瞻分析师预期 | Polygon/Massive 无此产品 |
| 期权 / 指数 / 外汇 / 加密 / 宏观经济 | 独立订阅 |

实际影响:`fundamentals` 表的 `pb_ratio` / `ps_ratio` / `shares_out` 列在 Starter
上 **没有数据源**——财报报表是 Advanced 档产品。`pe_ratio` 由 `earnings` 表推导、
`market_cap` 来自 ticker 详情端点,所以这两个无需报表即可覆盖。

### 采纳路线图

约定顺序(按价值÷成本)。仅 #1 已实现,其余暂缓。

1. SIC 板块 / 行业 —— **已完成**(`data/ingestion/sic_sectors.py` + `massive_marketcap.py`)。
2. Grouped Daily —— 一次调用做日线批量刷新。
3. 全市场快照 —— 热力图 / 筛选器涨跌幅即时化。
4. 分红 + 拆股 —— 公司行为数据 + 分红复权价格。
5. Top Movers —— 用涨跌幅榜快照做新 Dashboard 模块。
6. 空头持仓 / 成交量 —— 新情绪信号。
7. 相似公司 —— "相似股票" + chat agent 工具。
