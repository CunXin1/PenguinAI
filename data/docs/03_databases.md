# 03 · 数据库 / Databases

本仓库的数据有三种"可查询"形态:**① Parquet 文件(无需服务,最方便)**、
**② TimescaleDB(PostgreSQL 扩展,适合 SQL/横截面/服务化)**、**③ 其他 DB(规划中)**。

Three queryable forms: **① Parquet files (no server, easiest)**, **② TimescaleDB
(PostgreSQL extension, for SQL / cross-sectional / serving)**, **③ other DBs (planned)**.

---

## 中文

### 1. Parquet(最简单)
不需要任何数据库服务,直接用 pandas / pyarrow / DuckDB / polars 读。

```python
import pandas as pd
# 单只票全历史 + 指标(30 分钟)
df = pd.read_parquet(r"D:\BaiduNetdiskDownload\30min\by_symbol\stock\AAPL.parquet")
rth = df[df["rth"]]                       # 只看正股时段
print(rth[["et_time","adj_close","rsi_14","macd","vwap_day"]].tail())

# 日线
d = pd.read_parquet(r"D:\BaiduNetdiskDownload\30min\features_daily\stock\AAPL.parquet")

# 全市场宽表(Hive 数据集,可按分区裁剪)— 无指标
import pyarrow.dataset as ds
dset = ds.dataset(r"D:\BaiduNetdiskDownload\30min\parquet_market\bars_30m", partitioning="hive")
t = dset.to_table(filter=(ds.field("asset_type")=="stock") & (ds.field("year")==2024),
                  columns=["ts","symbol","adj_close"])
```
DuckDB 一行扫全宇宙:
```sql
SELECT symbol, count(*) FROM read_parquet('D:/BaiduNetdiskDownload/30min/by_symbol/stock/*.parquet')
GROUP BY symbol;
```

### 2. TimescaleDB(SQL)
镜像 `timescale/timescaledb-ha:pg17`,由 `docker-compose.yml` 起容器 `market_timescaledb`。
- 连接:`localhost:5432`,库 `market`,用户/密码 `postgres/postgres`(可用 `.env` 覆盖)。
- 数据随 Docker 卷 `market_pgdata` 持久化。

**启动 / 停止**
```powershell
cd timescale_market
docker compose up -d db          # 启动(数据保留)
docker compose stop db           # 停止(不丢数据)
docker compose down              # 删容器(卷仍在;down -v 才会删数据!)
docker exec market_timescaledb pg_isready -U postgres -d market   # 健康检查
```

**进 psql**
```powershell
docker exec -it market_timescaledb psql -U postgres -d market
```

#### 2.1 表结构(schema `sql/002_features_schema.sql`,当前生效版本)
- **`instruments`** — 标的维表:`instrument_id`(PK), `symbol`, `asset_type`('stock'|'etf'),
  `first_ts`, `last_ts`, `created_at`, `updated_at`。`UNIQUE(symbol, asset_type)`。
- **`bars_30m`** — 30 分钟 hypertable(按 `ts` 月分块):
  `ts`(timestamptz), `instrument_id`, `rth`(bool),
  `raw_open/high/low/close`(double), `raw_volume`(bigint),
  `adj_open/high/low/close`(double), `adj_volume`(bigint),
  + 19 指标列(`sma_20/50/200, ema_12/26/50, macd, macd_signal, macd_hist, rsi_14,
  bb_mid/upper/lower/pctb/bw, atr_14, obv, vwap_day, ret_1bar`)。
  主键 `(ts, instrument_id)`;二级索引 `(instrument_id, ts DESC)`。**只装 RTH bar**。
- **`bars_1d`** — 日线 hypertable(按 `ts` 年分块):
  `ts`(=当日最后 RTH bar 的 UTC 时间), `instrument_id`, `rth_bars`(int),
  `raw_close`, `adj_open/high/low/close`, `adj_volume`,
  + 指标(`sma/ema/macd/rsi/bb/atr/obv`)+ `ret_1d/5d/21d/63d/126d/252d` + `gap_overnight`。
- **`import_runs` / `import_files`** — 每次导入的记账(行数、状态、时间)。
- **`dataset_metadata`** — 键值元数据(bar 间隔、时区、schema 版本等)。
- **视图**:`v_bars_30m`、`v_bars_1d` —— 自动 join 出 `symbol, asset_type, et_time`,日常查询用视图最方便。

> 历史:`sql/001_schema.sql` 是早期版本(`bars_30m` 仅 raw/adj、无指标,且有 `v_bars_30m_long` 长表视图)。
> 当前数据库用的是 `002`,**没有 `v_bars_30m_long`**。`sql/020_query_examples.sql` 里少量示例针对 001,按需调整。

#### 2.2 现有数据量
- `bars_30m`:**236,664,512 行**,322 chunk,6,300 标的,最新 2026-06-03 15:30 ET。
- `bars_1d`:**19,553,926 行**,28 chunk,6,300 标的。
- `instruments`:6,300。

#### 2.3 常用查询
```sql
-- 某股最近日线指标
SELECT et_time::date AS d, adj_close, rsi_14, macd, ret_21d
FROM v_bars_1d WHERE symbol='AAPL' ORDER BY ts DESC LIMIT 10;

-- 横截面:最新交易日、RSI 超卖(<30)的股票
SELECT symbol, adj_close, rsi_14 FROM v_bars_1d
WHERE ts = (SELECT max(ts) FROM bars_1d) AND asset_type='stock' AND rsi_14 < 30
ORDER BY rsi_14 LIMIT 50;

-- 金叉:今日 macd 上穿 signal
WITH x AS (
  SELECT symbol, ts, macd, macd_signal,
         lag(macd-macd_signal) OVER (PARTITION BY instrument_id ORDER BY ts) AS prev_diff
  FROM v_bars_1d WHERE asset_type='stock')
SELECT symbol FROM x
WHERE ts=(SELECT max(ts) FROM bars_1d) AND (macd-macd_signal)>0 AND prev_diff<0;

-- 某股当日 30 分钟价 vs VWAP
SELECT et_time, adj_close, vwap_day FROM v_bars_30m
WHERE symbol='NVDA' AND ts >= now() - interval '2 days' ORDER BY ts;

-- 用 30 分钟重建任意周期日线(若想绕过 bars_1d)
SELECT symbol, time_bucket('1 day', ts, 'America/New_York') AS d,
       first(adj_open, ts) o, max(adj_high) h, min(adj_low) l,
       last(adj_close, ts) c, sum(adj_volume) v
FROM v_bars_30m WHERE symbol='AAPL' AND rth
GROUP BY symbol, d ORDER BY d;
```

#### 2.4 可选优化:压缩老数据
TimescaleDB 列式压缩能把老 chunk 缩小很多(2.37 亿行很值):
```sql
ALTER TABLE bars_30m SET (timescaledb.compress, timescaledb.compress_segmentby='instrument_id');
SELECT add_compression_policy('bars_30m', INTERVAL '90 days');
```
(默认没开;按需执行。)

### 3. 其他 DB(规划中)
- 目标里提过 "parquet + TimescaleDB + 其他 db"。**其他 DB 尚未实现**。候选:
  - **DuckDB**:把 by_symbol/features_daily 当外部 Parquet 直接查,零 ETL,适合本地分析。
  - **ClickHouse**:亿级行的列式 OLAP,横截面扫描快;可从 Parquet 直接 `INSERT ... FROM file`。
- 长表合并(一标的一 Parquet 同时含 1min/30min/日线 + 指标,用 `timeframe` 列区分)也在规划中,等 IBKR 1 分钟线到位再做。

---

## English

### 1. Parquet (easiest)
No DB server — read with pandas / pyarrow / DuckDB / polars. Examples mirror the Chinese section above:
`pd.read_parquet(by_symbol/<asset>/<SYMBOL>.parquet)`, filter `df["rth"]`; the Hive dataset
`parquet_market/bars_30m` supports partition pruning by `asset_type`/`year`; DuckDB can glob
`read_parquet('.../by_symbol/stock/*.parquet')`.

### 2. TimescaleDB (SQL)
Image `timescale/timescaledb-ha:pg17`, container `market_timescaledb` from `docker-compose.yml`.
Connect at `localhost:5432`, db `market`, `postgres/postgres`; data persists in volume `market_pgdata`.

Start/stop: `docker compose up -d db` / `stop db` / `down` (use `down -v` only to wipe data).
Shell: `docker exec -it market_timescaledb psql -U postgres -d market`.

**Schema (`sql/002_features_schema.sql`, current):**
- `instruments` — dimension (instrument_id PK, symbol, asset_type, first_ts, last_ts, UNIQUE(symbol,asset_type)).
- `bars_30m` — 30-min hypertable (monthly chunks): ts, instrument_id, rth, raw_*(5), adj_*(5) + 19 indicator
  columns; PK (ts, instrument_id); index (instrument_id, ts DESC). **RTH bars only.**
- `bars_1d` — daily hypertable (yearly chunks): ts (= day's last RTH bar UTC), instrument_id, rth_bars,
  raw_close, adj_*(5) + indicators + ret_1/5/21/63/126/252d + gap_overnight.
- `import_runs` / `import_files` — load bookkeeping; `dataset_metadata` — key/value metadata.
- Views `v_bars_30m` / `v_bars_1d` join symbol/asset_type/et_time — prefer these for queries.

> History: `sql/001_schema.sql` is the earlier raw/adj-only schema (had `v_bars_30m_long`). The live DB
> uses `002`; **`v_bars_30m_long` does not exist** there. `sql/020_query_examples.sql` has a few 001-era examples.

**Volumes:** bars_30m = 236,664,512 rows (322 chunks, 6,300 symbols, latest 2026-06-03 15:30 ET);
bars_1d = 19,553,926 rows (28 chunks, 6,300 symbols); instruments = 6,300.

**Common queries:** see the Chinese SQL block above (latest daily indicators; cross-sectional oversold;
MACD cross; intraday price-vs-VWAP; rebuild daily from 30-min via `time_bucket`).

**Optional compression** for old chunks (recommended for 236M rows): `ALTER TABLE bars_30m SET
(timescaledb.compress, timescaledb.compress_segmentby='instrument_id'); SELECT
add_compression_policy('bars_30m', INTERVAL '90 days');` (off by default).

### 3. Other DBs (planned)
Not implemented yet. Candidates: **DuckDB** (query the Parquet directly, zero ETL) and **ClickHouse**
(columnar OLAP for cross-sectional scans over 100M+ rows; `INSERT ... FROM` Parquet). The combined
long-table (one Parquet per symbol holding 1min/30min/daily + indicators, discriminated by a `timeframe`
column) is also planned once IBKR 1-minute data lands.
