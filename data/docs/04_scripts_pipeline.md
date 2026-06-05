# 04 · 脚本与流程 / Scripts & Pipeline

所有脚本在 `scripts/`。用仓库自带的 venv 运行:`timescale_market\.venv\Scripts\python.exe`。
多数脚本默认路径写死,**迁移后用 CLI 参数覆盖**。

All scripts in `scripts/`; run with the bundled venv. Default paths are hard-coded — **override via CLI flags after moving**.

---

## 中文

### 脚本清单(按管线顺序)
| 脚本 | 作用 | 输入 → 输出 |
|---|---|---|
| `build_parquet_copy.py` | 原始 zip/目录 → 宽表 Parquet(多进程 + pyarrow.csv,时区转 UTC) | 原始 → `parquet_market/` |
| `import_market_data.py` | 早期一体化导入器(逐文件,较旧;现已被下面分步流程取代) | 原始 → DB(legacy) |
| `symbol_stats.py` | 每标的 first/last_ts、n_bars、**退市判定**(按各资产类型自己的最新 bar) | `parquet_market` → `by_symbol/_symbol_stats.parquet` |
| `export_by_symbol.py` | 宽表 → **一标的一文件**(按 asset_type+首字母并行,run-end 切分) | `parquet_market` → `by_symbol/{stock,etf}/` |
| `liquidity_profile.py` | 每标的 **ADDV**(平均日成交额)+ 2026 末价 + 漏斗 | `parquet_market` → `by_symbol/_liquidity_<at>.parquet` |
| `build_universe.py` | 流动性宇宙规则(price≥$1 且 ADDV≥$1M),移出宇宙外文件 | → `_universe_<at>.*`,移动文件 |
| `compute_indicators.py` | 计算全部指标(RTH-only,基于 adj),写回 30 分钟 + 另出日线 | `by_symbol/` →(就地)+ `features_daily/` |
| `yahoo_fetch.py` | Yahoo 拉最近 30 分钟 bar,staging + **append-only 合并** | Yahoo → `yahoo_staging/` →(合并)`by_symbol/` |
| `yahoo_monitor.py` | 实时统计 Yahoo 拉取的成功/空/错误,写 `_failures.txt` | 读 checkpoint |
| `ibkr_fetch.py` | IBKR(ib_async)拉取(需登录 TWS/Gateway;**未在真账号上测过**) | IBKR → staging/合并 |
| `fill_adj_gap.py` | 把 `adj` 为空、`raw` 有值的行 `adj_* := raw_*`(补复权缺口) | `by_symbol/` 就地 |
| `filter_common_stock.py` | 用 NASDAQ 名录按证券类型过滤(剔除优先股/单位/债/权证) | → `_security_type_stock.parquet`,移动文件 |
| `prune_delisted.py` | 按合并后 last_ts 剔除"到不了最新"的退市标的 | 移动到 `*_delisted/` |
| `db_common.py` | DB 公共库:连接、建 schema、instruments、COPY 等(被导入器调用) | — |
| `import_parquet_to_timescale.py` | 暂存表 + GROUP BY + ON CONFLICT 的稳健 upsert 导入(raw/adj) | `parquet_market` → `bars_30m` |
| `import_parquet_fast.py` | drop 索引 + 直接 COPY(raw/adj,无指标) | `parquet_market` → `bars_30m` |
| `import_features_to_timescale.py` | ★**当前导入器**:并行 + drop-PK + 指标,装两张表 | `by_symbol`+`features_daily` → `bars_30m`+`bars_1d` |

### 从零完整复现(全量重建)
```powershell
$py = "D:\BaiduNetdiskDownload\30min\timescale_market\.venv\Scripts\python.exe"
cd D:\BaiduNetdiskDownload\30min\timescale_market\scripts

# 1) 原始 → 宽表 Parquet(多进程)
& $py build_parquet_copy.py --workers 12

# 2) 每标的统计 + 退市判定
& $py symbol_stats.py

# 3) 宽表 → 一标的一文件
& $py export_by_symbol.py --workers 8

# 4) 流动性指标 + 宇宙(股票、ETF 各跑一次)
& $py liquidity_profile.py --asset-type stock
& $py liquidity_profile.py --asset-type etf
& $py build_universe.py --asset-type stock   # price>=1 且 addv>=1M
& $py build_universe.py --asset-type etf --addv-floor 1000000

# 5) 证券类型过滤(剔除优先股等,保留混入的 ETF)
& $py filter_common_stock.py --apply --drop "preferred,warrant,unit,note,test"

# 6) 计算指标(30 分钟就地 + 日线)
& $py compute_indicators.py --scope all --workers 16

# 7)(可选)用 Yahoo 补到最新 + 回填复权缺口 + 重算 + 退市过滤
& $py yahoo_fetch.py --resume --merge
& $py fill_adj_gap.py --scope all
& $py compute_indicators.py --scope all
& $py prune_delisted.py --asset-type stock --apply
& $py prune_delisted.py --asset-type etf --apply

# 8) 起 DB 并导入(带指标的新 schema)
cd ..; docker compose up -d db; cd scripts
$env:PGHOST="localhost"; $env:PGPORT="5432"; $env:PGDATABASE="market"; $env:PGUSER="postgres"; $env:PGPASSWORD="postgres"
& $py import_features_to_timescale.py --init-schema --scope all --workers 10
```

### 日常"对齐到最新"刷新(增量)
```powershell
& $py yahoo_fetch.py --resume --merge          # 拉新 bar 并 append-only 合并
& $py fill_adj_gap.py --scope all              # 补任何 adj 空缺
& $py compute_indicators.py --scope all        # 重算指标
& $py prune_delisted.py --asset-type stock --apply
& $py prune_delisted.py --asset-type etf --apply
& $py import_features_to_timescale.py --init-schema --scope all --workers 10   # 重灌 DB
```

### 关键参数速查
- 通用:`--scope {all,stock,etf}`、`--workers N`、`--symbols A,B`、`--limit N`(冒烟)、`--dry-run`。
- `yahoo_fetch.py`:`--period 58d`(Yahoo 30 分钟硬上限 60 天!)、`--merge`、`--resume`、`--staging-dir`。
- `build_universe.py`:`--price-floor 1.0`、`--addv-floor 1000000`、`--no-move`。
- `filter_common_stock.py`:`--drop "preferred,warrant,unit,note,test"`(默认还含 etf;保留 ETF 就别带 etf)、`--apply`、`--refresh`。
- `prune_delisted.py`:`--stale-days 7`、`--apply`。
- `import_features_to_timescale.py`:`--init-schema`、`--workers 10`、`--all-bars`(默认只 RTH)、`--no-30min`/`--no-daily`。

---

## English

### Script list (pipeline order)
Same table as Chinese above. Summary:
`build_parquet_copy.py` (raw→wide Parquet), `symbol_stats.py` (per-symbol stats + delisting),
`export_by_symbol.py` (wide→per-symbol), `liquidity_profile.py` (ADDV), `build_universe.py` (liquidity
universe), `compute_indicators.py` (indicators → by_symbol in-place + features_daily),
`yahoo_fetch.py` / `yahoo_monitor.py` (Yahoo refresh + monitor), `ibkr_fetch.py` (IBKR alt, untested live),
`fill_adj_gap.py` (adj:=raw where NaN), `filter_common_stock.py` (security-type filter via NASDAQ directory),
`prune_delisted.py` (remove stale by last_ts), `db_common.py` (DB helpers),
`import_parquet_to_timescale.py` (staged upsert, raw/adj), `import_parquet_fast.py` (fast COPY, raw/adj),
**`import_features_to_timescale.py`** (current: parallel + drop-PK + indicators → bars_30m + bars_1d).

### Full rebuild from scratch
See the PowerShell block in the Chinese section (steps 1–8). Note: run `liquidity_profile.py` and
`build_universe.py` once per `--asset-type`; the DB step needs `docker compose up -d db` + PG env vars.

### Incremental "align to latest" refresh
`yahoo_fetch.py --resume --merge` → `fill_adj_gap.py --scope all` → `compute_indicators.py --scope all`
→ `prune_delisted.py --asset-type {stock,etf} --apply` → `import_features_to_timescale.py --init-schema --scope all --workers 10`.

### Key flags
Common: `--scope`, `--workers`, `--symbols`, `--limit`, `--dry-run`. Yahoo: `--period 58d` (**Yahoo 30-min
hard cap is 60 days!**), `--merge`, `--resume`. Universe: `--price-floor`, `--addv-floor`. Filter:
`--drop "preferred,warrant,unit,note,test"`, `--apply`, `--refresh`. Prune: `--stale-days`, `--apply`.
Importer: `--init-schema`, `--workers`, `--all-bars` (default RTH-only), `--no-30min`/`--no-daily`.
