# 美股 30 分钟数据管线 · 文档总览 / US Equity 30-min Data Pipeline · Docs Index

> 本仓库把 ~7000 只美股 + ~5000 只 ETF 的 **30 分钟 K 线**(2000–2026)归一化为
> Parquet 与 TimescaleDB,计算十几种技术指标,过滤出一个干净的"可推荐宇宙",
> 目标是支撑一个**美股 AI 推荐系统(只推荐、不交易)**。
>
> This repo normalizes ~7,000 US stocks + ~5,000 ETFs of **30-minute bars**
> (2000–2026) into Parquet and TimescaleDB, computes ~20 technical indicators, and
> filters a clean "recommendable universe" to power a **US-equity AI recommendation
> system (recommend-only, no trading)**.

---

## 中文

### 一句话现状(截至 2026-06-04)
- **原始 → Parquet → 单标的 Parquet(带指标)→ TimescaleDB** 全链路已打通。
- 数据已用 Yahoo 补齐并**对齐到 2026-06-03**;复权序列 2000→今连续。
- 最终宇宙:**4,167 只普通股 + 2,133 只 ETF = 6,300 个标的**(已剔除优先股/SPAC 单位/baby-bond/权证/退市)。
- TimescaleDB 已装载:`bars_30m` 2.37 亿行 + `bars_1d` 1,955 万行,均带指标。

### 文档目录
| 文件 | 内容 |
|---|---|
| [CHEATSHEET.md](CHEATSHEET.md) | **速查表**:一页纸的常用路径/命令/SQL/关键数字/坑 |
| [01_data_dictionary.md](01_data_dictionary.md) | **数据字典**:所有数据产物、目录布局、每个字段的含义与类型 |
| [02_indicators.md](02_indicators.md) | **指标计算**:20+ 指标的精确公式、参数、口径与注意点 |
| [03_databases.md](03_databases.md) | **数据库**:TimescaleDB 表/视图/索引、Parquet 用法、查询示例、其他 DB 选项 |
| [04_scripts_pipeline.md](04_scripts_pipeline.md) | **脚本与流程**:每个脚本作用、参数、运行顺序、从零复现 |
| [05_sources_and_refresh.md](05_sources_and_refresh.md) | **数据源与刷新**:原始 zip/目录、Yahoo/IBKR 增量、符号格式、各种坑 |
| [06_setup_and_operations.md](06_setup_and_operations.md) | **环境与运维**:venv、Docker、迁移 repo、备份恢复 |

### 顶层目录布局
```
30min/                              ← 数据根(大)
├── 2000.zip ... 2026.zip          原始未复权股票(每年一个 zip)
├── 2000(1).zip ... 2026(1).zip    原始拆股+分红复权股票
├── etf_full_30min_<A..Z>/         原始未复权 ETF(按首字母分目录)
├── etf_full_30min_<A..Z>_adj_splitdiv/   复权 ETF
├── 数据介绍.txt                    数据供应商的格式说明
├── parquet_market/                宽表 Parquet(Hive 分区,raw+adj,无指标)
├── by_symbol/                     一标的一文件(30 分钟 + 指标)★主产物
│   ├── stock/  (4,167)            纯普通股宇宙
│   ├── etf/    (2,133)            ETF 宇宙
│   ├── stock_noncommon/ (128)     被剔除:优先股/单位/债/权证(可逆)
│   ├── stock_delisted/ (23)       被剔除:退市股(可逆)
│   ├── etf_delisted/   (3)        被剔除:退市 ETF(可逆)
│   ├── _nasdaq/                   NASDAQ 证券名录缓存
│   └── _*.parquet / _*.txt        清单与统计(见数据字典)
├── features_daily/                一标的一文件(日线 + 指标 + 多周期收益)
│   ├── stock/ (4,167)  etf/ (2,133)
│   └── _stale/                    prune 后过期的日线(可删)
├── yahoo_staging/, yahoo_staging2/  Yahoo 拉取暂存
└── timescale_market/              ← 代码仓库(要迁走的部分)
    ├── scripts/                   所有 Python 脚本
    ├── sql/                       schema 与查询示例
    ├── docs/                      本文档
    ├── docker-compose.yml         TimescaleDB 容器
    ├── Dockerfile.loader          容器内导入器(可选)
    ├── requirements.txt, run_local.ps1
    └── .venv/                     Python 虚拟环境
```

> ⚠️ **路径说明**:脚本里默认路径写死为 `D:\BaiduNetdiskDownload\30min\...`。
> 迁移后请用每个脚本的命令行参数(如 `--parquet-root`、`--by-symbol-root`)覆盖,
> 或全局改这些默认值。详见 [06_setup_and_operations.md](06_setup_and_operations.md)。

---

## English

### Status in one line (as of 2026-06-04)
- Full chain **raw → Parquet → per-symbol Parquet (with indicators) → TimescaleDB** is working.
- Data refreshed from Yahoo and **aligned to 2026-06-03**; adjusted series continuous 2000→now.
- Final universe: **4,167 common stocks + 2,133 ETFs = 6,300 symbols** (preferred/SPAC-unit/
  baby-bond/warrant/delisted removed).
- TimescaleDB loaded: `bars_30m` 236.6M rows + `bars_1d` 19.55M rows, both with indicators.

### Doc map
| File | Content |
|---|---|
| [CHEATSHEET.md](CHEATSHEET.md) | **Cheat sheet**: one-page paths/commands/SQL/key numbers/gotchas |
| [01_data_dictionary.md](01_data_dictionary.md) | **Data dictionary**: every artifact, directory layout, field meanings & types |
| [02_indicators.md](02_indicators.md) | **Indicators**: exact formulas, parameters, conventions, caveats |
| [03_databases.md](03_databases.md) | **Databases**: TimescaleDB tables/views/indexes, Parquet usage, query examples |
| [04_scripts_pipeline.md](04_scripts_pipeline.md) | **Scripts & pipeline**: each script, args, run order, reproduce from scratch |
| [05_sources_and_refresh.md](05_sources_and_refresh.md) | **Sources & refresh**: raw zips/dirs, Yahoo/IBKR incremental, symbol formats, gotchas |
| [06_setup_and_operations.md](06_setup_and_operations.md) | **Setup & ops**: venv, Docker, moving the repo, backup/restore |

See the directory layout above (same for both languages). **Paths in scripts default to
`D:\BaiduNetdiskDownload\30min\...`; override via CLI flags after moving the repo.**
