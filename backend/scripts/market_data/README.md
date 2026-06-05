# TimescaleDB + Parquet market data organizer

> 📚 **完整文档见 [`docs/`](docs/README.md)**(中英双语,详细):数据字典、指标公式、数据库用法、
> 脚本与流程、数据源刷新、环境与迁移。本 README 下方为**早期速览**(部分内容对应旧的 `001` schema,
> 当前生效的是带指标的 `002`,以 `docs/` 为准)。
>
> 📚 **Full docs: [`docs/`](docs/README.md)** (bilingual, detailed). The README below is an **early quick
> overview**; some of it reflects the old `001` schema — the live DB uses the indicator-rich `002`. Trust `docs/`.

---

这个目录把当前美股 30 分钟数据整理成两份东西：

- 原始数据：保留不动，`2000.zip`、`2000(1).zip`、ETF CSV 目录都不删除、不移动。
- Parquet 副本：默认输出到 `D:\BaiduNetdiskDownload\30min\parquet_market`。
- TimescaleDB：从 Parquet 副本导入，股票和 ETF 在同一个数据库、同一张行情 hypertable 里。

## TimescaleDB 行和列

主表是 `bars_30m`。

一行代表：

```text
一个时间点 ts + 一个标的 instrument_id
```

也就是不是“一只股票一列”，而是所有股票和 ETF 纵向堆在同一张表里。这样 TimescaleDB 可以按时间分区、按时间查询和压缩。

主要列：

```text
ts
instrument_id
raw_open, raw_high, raw_low, raw_close, raw_volume
adj_open, adj_high, adj_low, adj_close, adj_volume
inserted_at, updated_at
```

`instruments` 表保存标的信息：

```text
instrument_id
symbol
asset_type   -- stock 或 etf
first_ts
last_ts
```

所以 AAPL 和 SPY 都在同一个 `bars_30m` 表里，用 `asset_type` 区分股票/ETF。复权不是单独多一行，而是同一行里的 `adj_*` 列；未复权在 `raw_*` 列。

`ts` 是 Timescale hypertable 的时间列，按 1 个月 chunk 分区。源 CSV 的时间是美国东部时间，导入时会解释成 `America/New_York` 并存成 `TIMESTAMPTZ`。

## Parquet 副本结构

Parquet 副本也是宽表。文件体里的列（不含分区键）：

```text
ts, et_time, symbol,
raw_open, raw_high, raw_low, raw_close, raw_volume,
adj_open, adj_high, adj_low, adj_close, adj_volume
```

`year`、`asset_type`、`bucket` 只编码在 Hive 目录路径里，不写进文件体。
这样 `pandas.read_parquet(目录)`、`pyarrow.dataset`、DuckDB 等标准读法会从路径
自动还原这三列，不会和文件内的物理列发生类型冲突。

默认目录按时间和类型分区：

```text
parquet_market/
  bars_30m/
    year=2024/
      asset_type=stock/
        bucket=A/
          part-000000.parquet
      asset_type=etf/
        bucket=S/
          part-000000.parquet
```

每个 Parquet part 内部按 `ts` 排序。

## 不用 Docker 的本机运行方式

可以不用 Docker。分两种情况：

- 生成 Parquet 副本：只需要 Python + `pyarrow`，完全不需要 TimescaleDB。
- 导入 TimescaleDB：需要你已经有一个能连接的 PostgreSQL + TimescaleDB 服务，可以是本机、WSL、局域网服务器或云数据库。

在 `timescale_market` 目录运行下面命令会自动创建 `.venv` 并安装依赖：

```powershell
.\run_local.ps1 -Command build-parquet -Years 2024 -Symbols AAPL,SPY -Overwrite
```

全量生成 Parquet 副本：

```powershell
.\run_local.ps1 -Command build-parquet -Overwrite
```

如果要导入 TimescaleDB，先设置连接信息：

```powershell
$env:PGHOST="localhost"
$env:PGPORT="5432"
$env:PGDATABASE="market"
$env:PGUSER="postgres"
$env:PGPASSWORD="postgres"
```

初始化 schema：

```powershell
.\run_local.ps1 -Command init-schema
```

从 Parquet 导入：

```powershell
.\run_local.ps1 -Command import-parquet -InitSchema
```

查一下导入结果：

```powershell
.\run_local.ps1 -Command query
```

## Docker 运行方式

在 `timescale_market` 目录运行：

```powershell
docker compose up -d db
```

初始化 schema：

```powershell
docker compose exec -T db psql -U postgres -d market -f /sql/001_schema.sql
```

## 先生成小 Parquet 副本

建议先用 AAPL 和 SPY 的 2024 年数据试跑：

```powershell
docker compose run --rm loader /app/scripts/build_parquet_copy.py --data-root /data --output-root /data/parquet_market --years 2024 --symbols AAPL,SPY --overwrite
```

这一步只会创建或重建 `/data/parquet_market`，不会改原始 zip/CSV。

## 从 Parquet 导入 TimescaleDB

```powershell
docker compose run --rm loader /app/scripts/import_parquet_to_timescale.py --parquet-root /data/parquet_market --init-schema
```

查看导入结果：

```powershell
docker compose exec -T db psql -U postgres -d market -c "select symbol, asset_type, count(*) from v_bars_30m group by 1,2 order by 1,2;"
```

## 全量流程

先生成全量 Parquet 副本：

```powershell
docker compose run --rm loader /app/scripts/build_parquet_copy.py --data-root /data --output-root /data/parquet_market --overwrite
```

再导入 TimescaleDB：

```powershell
docker compose run --rm loader /app/scripts/import_parquet_to_timescale.py --parquet-root /data/parquet_market --init-schema
```

只做股票：

```powershell
docker compose run --rm loader /app/scripts/build_parquet_copy.py --data-root /data --output-root /data/parquet_market --scope stocks --overwrite
```

只做 ETF：

```powershell
docker compose run --rm loader /app/scripts/build_parquet_copy.py --data-root /data --output-root /data/parquet_market --scope etfs --overwrite
```

## 查询样例

宽表查询：

```sql
SELECT *
FROM v_bars_30m
WHERE symbol = 'AAPL'
  AND asset_type = 'stock'
ORDER BY ts DESC
LIMIT 50;
```

只看复权价格：

```sql
SELECT et_time, symbol, adj_open, adj_high, adj_low, adj_close, adj_volume
FROM v_bars_30m
WHERE symbol = 'AAPL'
  AND asset_type = 'stock'
ORDER BY ts DESC
LIMIT 50;
```

如果某个回测库更喜欢“复权/未复权作为行”的格式，可以用视图 `v_bars_30m_long`。

## 加速版（多进程 + 直连 COPY）

### 生成 Parquet：多进程并行 + pyarrow 解析

`build_parquet_copy.py` 默认就并行了（`--workers` 默认 `min(8, CPU 核数)`）：

- 股票按**年**切分给不同进程，ETF 按**首字母桶**切分，各进程写互不相交的分区，不会撞文件名。
- CSV 用 `pyarrow.csv` 向量化解析（比纯 Python `csv` 快很多），时区转换走 Python `zoneinfo`（pyarrow 在 Windows 上没带 IANA 时区库）。
- 每个进程结束时把自己负责的分区**完整刷盘**，避免旧版"残留缓冲撑满、被迫小块刷盘"导致的碎文件问题——文件更少更大。

实测：股票 2000–2005 六年，单线程 333s → 6 进程 **60s（约 5.5×）**，行数完全一致。

```powershell
.\run_local.ps1 -Command build-parquet -Overwrite          # 默认多进程
# 或直接调脚本指定进程数：
.\.venv\Scripts\python.exe .\scripts\build_parquet_copy.py `
  --data-root .. --output-root ..\parquet_market --workers 12 --overwrite
```

`--row-group-rows`（默认 25 万，每个 part 文件的行数）和 `--max-buffer-rows`（默认 400 万，每进程内存上限）可调。

### 导入 TimescaleDB：直连 COPY + 临时删索引

`import_parquet_fast.py` 是加速版导入：

- **导入期临时 DROP 两个二级索引**，导完一次性重建（避免边插边维护索引），可用 `--keep-indexes` 关闭。
- **直接 `COPY` 进 `bars_30m`**：Parquet 里 raw/adj 已合并成一行、`(ts,instrument_id)` 全局唯一，不需要旧版的 stage 表 + `GROUP BY` + `ON CONFLICT` 合并。
- 会话级 `synchronous_commit=off`，导完刷新 `instruments` 时间范围并 `ANALYZE`。

```powershell
.\.venv\Scripts\python.exe .\scripts\import_parquet_fast.py `
  --parquet-root ..\parquet_market --init-schema
```

> 主键 `(ts, instrument_id)` 在导入期保留，作为唯一性保证；若数据真有重复，COPY 会直接报错而不是悄悄吞掉。原 `import_parquet_to_timescale.py` 仍保留（带 upsert 合并，适合增量/可能有重复的场景）。
