# 速查表 / Cheat Sheet

一页纸:最常用的路径、命令、SQL、关键数字、坑。详见同目录其它文档。
One page: paths, commands, SQL, key numbers, gotchas. Full detail in the other docs.

---

## 关键数字 / Key numbers
- 宇宙 Universe: **4,167 stocks + 2,133 ETFs = 6,300**;数据到 **2026-06-03**(对齐最新)。
- TimescaleDB: `bars_30m` 236.6M 行 / `bars_1d` 19.55M 行(均带指标,RTH-only)。
- 30 分钟一天 13 根 RTH bar(09:30–15:30);价格 `adj_*` 复权,`raw_*` 未复权;`ts`=UTC,`et_time`=美东。

## 关键路径 / Key paths
```
by_symbol\stock\<SYM>.parquet        30分钟 + 指标(主产物)
features_daily\stock\<SYM>.parquet   日线 + 指标 + 多周期收益
parquet_market\bars_30m\...          全市场宽表(Hive,无指标)
timescale_market\scripts\            脚本    | \sql\  schema   | \docs\  文档
```

## 环境 / Env (PowerShell)
```powershell
$py = "D:\BaiduNetdiskDownload\30min\timescale_market\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING="utf-8"
$env:PGHOST="localhost"; $env:PGPORT="5432"; $env:PGDATABASE="market"; $env:PGUSER="postgres"; $env:PGPASSWORD="postgres"
cd D:\BaiduNetdiskDownload\30min\timescale_market\scripts
```

## 启停数据库 / DB start-stop
```powershell
cd ..\; docker compose up -d db ; cd scripts          # 起(数据保留)
docker exec market_timescaledb pg_isready -U postgres -d market
docker exec -it market_timescaledb psql -U postgres -d market   # 进 psql
# docker compose stop db   停 ; docker compose down -v  删数据(慎用!)
```

## 增量刷新到最新 / Incremental refresh (run in order)
```powershell
& $py yahoo_fetch.py --resume --merge            # 拉 Yahoo + append-only 合并(30分钟硬上限60天,尽早跑!)
& $py fill_adj_gap.py --scope all                # 补复权空缺(adj:=raw)
& $py compute_indicators.py --scope all          # 重算指标(30分钟就地 + 日线)
& $py prune_delisted.py --asset-type stock --apply
& $py prune_delisted.py --asset-type etf --apply
& $py import_features_to_timescale.py --init-schema --scope all --workers 10   # 重灌 DB
& $py yahoo_monitor.py --watch 15                # (另开窗)看拉取进度
```

## 进度自查 / Progress checks
```powershell
docker exec market_timescaledb psql -U postgres -d market -c "SELECT count(*) FROM bars_30m;"
& $py yahoo_monitor.py                            # Yahoo 成功/空/错误
```

## 常用 SQL / Handy SQL (via v_bars_30m / v_bars_1d)
```sql
-- 某股最近日线指标
SELECT et_time::date d, adj_close, rsi_14, macd, ret_21d
FROM v_bars_1d WHERE symbol='AAPL' ORDER BY ts DESC LIMIT 10;
-- 横截面:最新日 RSI 超卖
SELECT symbol, adj_close, rsi_14 FROM v_bars_1d
WHERE ts=(SELECT max(ts) FROM bars_1d) AND asset_type='stock' AND rsi_14<30 ORDER BY rsi_14 LIMIT 50;
-- 日内价 vs VWAP
SELECT et_time, adj_close, vwap_day FROM v_bars_30m
WHERE symbol='NVDA' AND ts>=now()-interval '2 days' ORDER BY ts;
```

## Parquet 直读(无需 DB) / Read Parquet directly
```python
import pandas as pd
df = pd.read_parquet(r"D:\BaiduNetdiskDownload\30min\by_symbol\stock\AAPL.parquet")
rth = df[df["rth"]]          # 只看正股时段
```

## 坑 / Gotchas
- Yahoo 30 分钟**只回溯 60 天**;`period=58d` 偶尔假超限 → 用 `--period 25d` 重取救回。
- Yahoo 盘前盘后**成交量=0**(指标只用 RTH,无碍)。
- 代码格式各源不同:本集 `BRK.B` / Yahoo `BRK-B` / NASDAQ `BRK$B`;`PRN`→文件 `PRN_.parquet`。
- 指标**只在 adj 非空的 RTH 行**算(否则 ewm 类会冻结沿用旧值)。
- PowerShell `Remove-Item *.parquet` 通配可能被拦 → 用 Python `os/shutil` 删。
- 迁移后:全局替换路径 `D:\BaiduNetdiskDownload\30min` → 新根;重建 `.venv`;DB 用 `--init-schema` 重导。

## 从零全量重建 / Full rebuild
见 [04_scripts_pipeline.md](04_scripts_pipeline.md) §"从零完整复现"(步骤 1–8)。
See [04_scripts_pipeline.md](04_scripts_pipeline.md) "Full rebuild from scratch" (steps 1–8).
