# 01 · 数据字典 / Data Dictionary

本篇逐一说明每个数据产物的**布局、字段、类型、口径**。
This document describes every data artifact: **layout, fields, types, conventions.**

---

## 中文

### 0. 全局约定
- **K 线粒度**:30 分钟。bar 用**时段开始时间**标注(09:30 的 bar = 09:30:00–09:59:59)。
- **时区**:原始为美东时间(US/Eastern)。入库统一存 **UTC**(`ts`),并保留**美东墙钟**(`et_time`,无时区)。
- **正股时段(RTH)**:09:30–16:00。一个交易日 13 根 RTH bar(09:30,10:00,…,15:30)。
- **盘前盘后**:原始数据含 04:00–20:00;只有有成交的 bar 才存在(零成交量被供应商省略)。
- **复权**:`raw_*` = 未复权(真实成交价);`adj_*` = **拆股+分红复权**(回溯复权,近端 adj≈raw)。
- **成交量**:个股股数。本数据集里 `raw_volume == adj_volume`(同一笔成交)。
- **价格类型**:双精度浮点;成交量:64 位整数。

### 1. 原始数据(数据供应商,只读)
- **股票**:`YYYY.zip`(未复权)、`YYYY(1).zip`(复权),2000–2026,每年一个。解压后是按代码分的 CSV。
- **ETF**:`etf_full_30min_<A..Z>/`(未复权)、`etf_full_30min_<A..Z>_adj_splitdiv/`(复权),按首字母分目录。
- **CSV 列**(无表头,见 `数据介绍.txt`):
  `DateTime(yyyy-MM-dd HH:mm:ss, 美东), Open, High, Low, Close, Volume`
- 注意:**零成交量的时间没有行**(数据序列里的空缺=当时无成交)。

### 2. `parquet_market/` — 宽表 Parquet(Hive 分区)
中间产物。一行 = 一个 (ts, 标的)。**不含指标**。
- 布局:`parquet_market/bars_30m/year=YYYY/asset_type=stock|etf/bucket=<首字母>/part-*.parquet`
- `year` / `asset_type` / `bucket` 是**路径分区,不是物理列**(读 dataset 时自动重建)。
- 物理字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts` | timestamp[us, UTC] | bar 开始时间(UTC) |
| `et_time` | timestamp[us] | 美东墙钟(无 tz) |
| `symbol` | string | 代码 |
| `raw_open/high/low/close` | double | 未复权 OHLC |
| `raw_volume` | int64 | 成交量(股) |
| `adj_open/high/low/close` | double | 复权 OHLC |
| `adj_volume` | int64 | 复权成交量(=raw_volume) |

规模:~3.82 亿行,2,431 文件,~13.75 GB。

### 3. `by_symbol/` — 一标的一文件 + 指标 ★主产物
每个文件是**一只标的的完整 30 分钟历史(2000→最新)**,含 raw、adj 与全部指标。
- 路径:`by_symbol/<stock|etf>/<SYMBOL>.parquet`(代码即文件名;Windows 保留名特殊处理,见下)。
- **字段(共 33 列)**:

| 组 | 字段 | 类型 | 说明 |
|---|---|---|---|
| 时间/标识 | `ts` | ts[us,UTC] | bar 开始(UTC) |
| | `et_time` | ts[us] | 美东墙钟 |
| | `symbol` | string | 代码 |
| | `rth` | bool | 是否正股时段[09:30,16:00) |
| 未复权 | `raw_open/high/low/close` | double | |
| | `raw_volume` | int64 | |
| 复权 | `adj_open/high/low/close` | double | 指标都基于 adj |
| | `adj_volume` | int64 | |
| 均线 | `sma_20`,`sma_50`,`sma_200` | double | adj_close 简单均线(bar 数) |
| | `ema_12`,`ema_26`,`ema_50` | double | 指数均线 |
| MACD | `macd`,`macd_signal`,`macd_hist` | double | 12/26/9 |
| 动量 | `rsi_14` | double | Wilder RSI |
| 布林 | `bb_mid`,`bb_upper`,`bb_lower` | double | 20,2σ |
| | `bb_pctb`,`bb_bw` | double | %B、带宽 |
| 波动 | `atr_14` | double | Wilder ATR |
| 量价 | `obv` | double | 能量潮 |
| | `vwap_day` | double | **按交易日重置**的日内 VWAP |
| 收益 | `ret_1bar` | double | 相邻 bar 收益率 |

- **指标只在 RTH 行上计算**;盘前盘后行 `rth=false`、指标为 `NULL`/NaN。
- 公式细节见 [02_indicators.md](02_indicators.md)。

#### 3.1 被剔除的子目录(可逆,均为"移动"而非删除)
| 目录 | 数量 | 含义 |
|---|---|---|
| `by_symbol/stock_noncommon/` | 128 | 非普通股:优先股 80 + SPAC 单位 28 + baby-bond 债 16 + 权证 2 + 手动 C.K/APADU |
| `by_symbol/stock_delisted/` | 23 | 退市/Yahoo 无近期数据(含已改名 BK→BNY、SPAC 已合并等) |
| `by_symbol/etf_delisted/` | 3 | 退市 ETF(ETQ/ERNZ/SIXG) |

#### 3.2 清单与统计文件(`by_symbol/_*`)
| 文件 | 内容 |
|---|---|
| `_symbol_stats.parquet` | 每标的 first_ts/last_ts/n_bars + active 标志(退市判定) |
| `_liquidity_stock.parquet` / `_liquidity_etf.parquet` | 每标的 `addv`(平均日成交额)、`px_2026_last`、`n_days` |
| `_universe_stock.parquet` / `_universe_etf.parquet` | 流动性宇宙清单(含 `in_universe` 布尔列) |
| `_universe_stock.txt` / `_universe_etf.txt` | 上面对应的纯文本代码列表(流动性过滤后) |
| `_security_type_stock.parquet` | 每股票的证券类型(common/preferred/unit/note/warrant/etf/...) |
| `_universe_stock_common.txt` | 证券类型过滤后的普通股列表(4,167) |
| `_universe_etf_common.txt` | 退市过滤后的 ETF 列表(2,133) |
| `_nasdaq/nasdaqlisted.txt`,`_nasdaq/otherlisted.txt` | NASDAQ 官方证券名录缓存(证券类型分类的依据) |

### 4. `features_daily/` — 一标的一文件(日线)
由 30 分钟 RTH bar 按**交易日 resample** 得来,含日线指标 + 多周期收益。
- 路径:`features_daily/<stock|etf>/<SYMBOL>.parquet`
- **字段**:

| 组 | 字段 | 类型 | 说明 |
|---|---|---|---|
| 标识 | `symbol` | string | |
| | `asset_type` | string | stock/etf |
| | `date` | ts[us] | 交易日(美东午夜,naive) |
| | `last_ts` | ts[us,UTC] | 当日最后一根 RTH bar 的 UTC 时间(入库用作 ts) |
| | `rth_bars` | int64 | 当日 RTH bar 数(半日市<13) |
| 日 OHLCV | `adj_open/high/low/close` | double | 当日复权 O=首/H=max/L=min/C=末 |
| | `adj_volume` | int64 | 当日成交量合计 |
| | `raw_close` | double | 当日未复权收盘(末) |
| 指标 | `sma_20/50/200`,`ema_12/26/50` | double | 单位为**天** |
| | `macd`,`macd_signal`,`macd_hist`,`rsi_14` | double | |
| | `bb_mid/upper/lower/pctb/bw`,`atr_14`,`obv` | double | |
| 收益 | `ret_1d`,`ret_5d`,`ret_21d`,`ret_63d`,`ret_126d`,`ret_252d` | double | 多周期复权收益 |
| | `gap_overnight` | double | 今开/昨收−1 |

- 日线**没有** `vwap_day`(日内概念)。

### 5. TimescaleDB(见 [03_databases.md](03_databases.md))
- `bars_30m`:= by_symbol(RTH-only)入库,主键 (ts, instrument_id)。
- `bars_1d`:= features_daily 入库。
- `instruments`:代码 ↔ instrument_id 维表。
- `import_runs` / `import_files` / `dataset_metadata`:导入记账与元数据。
- 视图 `v_bars_30m` / `v_bars_1d`:join 出 symbol/asset_type/et_time。

---

## English

### 0. Global conventions
- **Granularity**: 30-minute bars, labeled by **period start** (the 09:30 bar covers 09:30:00–09:59:59).
- **Timezone**: source is US/Eastern. Stored as **UTC** (`ts`) plus the **ET wall-clock** (`et_time`, naive).
- **Regular Trading Hours (RTH)**: 09:30–16:00 → 13 bars/day (09:30,10:00,…,15:30).
- **Extended hours**: source spans 04:00–20:00; a bar exists only if it traded (zero-volume bars omitted by the vendor).
- **Adjustment**: `raw_*` = unadjusted; `adj_*` = **split+dividend back-adjusted** (adj≈raw at the recent anchor).
- **Volume**: individual shares; `raw_volume == adj_volume` in this dataset.
- **Types**: prices = double precision; volumes = int64.

### 1. Raw vendor data (read-only)
- **Stocks**: `YYYY.zip` (unadjusted), `YYYY(1).zip` (adjusted), one per year 2000–2026; CSV-per-symbol inside.
- **ETFs**: `etf_full_30min_<A..Z>/` (unadjusted), `etf_full_30min_<A..Z>_adj_splitdiv/` (adjusted), bucketed by first letter.
- **CSV columns** (headerless, see `数据介绍.txt`): `DateTime(yyyy-MM-dd HH:mm:ss, ET), Open, High, Low, Close, Volume`.
- **Zero-volume timestamps have no row** (gaps = no trades).

### 2. `parquet_market/` — wide Parquet (Hive-partitioned)
Intermediate. One row = one (ts, instrument). **No indicators.**
- Layout: `bars_30m/year=YYYY/asset_type=stock|etf/bucket=<first-letter>/part-*.parquet`.
- `year` / `asset_type` / `bucket` are **path partitions, not physical columns** (reconstructed when reading the dataset).
- Physical columns: `ts` (ts[us,UTC]), `et_time` (ts[us]), `symbol` (string), `raw_open/high/low/close` (double),
  `raw_volume` (int64), `adj_open/high/low/close` (double), `adj_volume` (int64).
- Scale: ~381.8M rows, 2,431 files, ~13.75 GB.

### 3. `by_symbol/` — one file per symbol + indicators ★main artifact
Each file = one symbol's full 30-min history (2000→latest) with raw, adj and all indicators.
- Path: `by_symbol/<stock|etf>/<SYMBOL>.parquet`.
- **33 columns**: the base 13 (`ts, et_time, symbol, raw_*(5), adj_*(5)`) + `rth` (bool) + 19 indicators:
  `sma_20/50/200, ema_12/26/50, macd, macd_signal, macd_hist, rsi_14, bb_mid, bb_upper, bb_lower, bb_pctb,
  bb_bw, atr_14, obv, vwap_day, ret_1bar`. All doubles.
- **Indicators are computed only on RTH rows**; extended-hours rows have `rth=false` and NULL/NaN indicators.
- Formulas: see [02_indicators.md](02_indicators.md).

#### 3.1 Excluded sub-dirs (reversible — files are MOVED, not deleted)
- `stock_noncommon/` (128): non-common = 80 preferred + 28 SPAC units + 16 baby-bond notes + 2 warrants + manual C.K/APADU.
- `stock_delisted/` (23): delisted / no recent Yahoo data (incl. BK→renamed BNY, merged SPACs).
- `etf_delisted/` (3): ETQ/ERNZ/SIXG.

#### 3.2 Manifest & stats files (`by_symbol/_*`)
- `_symbol_stats.parquet` — per-symbol first/last_ts, n_bars, active flag (delisting).
- `_liquidity_{stock,etf}.parquet` — per-symbol `addv` (avg daily dollar volume), `px_2026_last`, `n_days`.
- `_universe_{stock,etf}.parquet` (+ `.txt`) — liquidity-filtered universe with an `in_universe` flag.
- `_security_type_stock.parquet` — per-stock security type (common/preferred/unit/note/warrant/etf/…).
- `_universe_stock_common.txt` (4,167), `_universe_etf_common.txt` (2,133) — final kept lists.
- `_nasdaq/{nasdaqlisted,otherlisted}.txt` — cached NASDAQ symbol directory (basis for security typing).

### 4. `features_daily/` — one file per symbol (daily)
Resampled from 30-min RTH bars per trading day; daily indicators + multi-horizon returns.
- Path: `features_daily/<stock|etf>/<SYMBOL>.parquet`.
- Columns: `symbol, asset_type, date (ts[us] naive ET midnight), last_ts (ts[us,UTC]), rth_bars (int64),
  adj_open/high/low/close (double), adj_volume (int64), raw_close (double)`, then daily indicators
  (`sma_20/50/200, ema_12/26/50, macd, macd_signal, macd_hist, rsi_14, bb_mid/upper/lower/pctb/bw, atr_14, obv`)
  and returns (`ret_1d, ret_5d, ret_21d, ret_63d, ret_126d, ret_252d, gap_overnight`). Periods are in **days**.
- Daily has **no** `vwap_day` (intraday-only).

### 5. TimescaleDB (see [03_databases.md](03_databases.md))
- `bars_30m` ← by_symbol (RTH-only), PK (ts, instrument_id).
- `bars_1d` ← features_daily.
- `instruments` — symbol ↔ instrument_id dimension.
- `import_runs` / `import_files` / `dataset_metadata` — bookkeeping & metadata.
- Views `v_bars_30m` / `v_bars_1d` — join symbol/asset_type/et_time.
