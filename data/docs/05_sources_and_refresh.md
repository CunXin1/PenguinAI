# 05 · 数据源与刷新 / Data Sources & Refresh

如何把数据**补到最新**、各数据源的特性、符号格式差异,以及一路踩过的**所有坑**。
How to **bring data up to date**, the quirks of each source, symbol-format differences, and every **gotcha** learned.

---

## 中文

### 1. 三个数据源对比
| 源 | 用途 | 复权 | 历史深度 | 限制 / 坑 |
|---|---|---|---|---|
| **供应商 zip/目录** | 初始全量(2000–2026) | raw + adj 分两套文件 | 全 | 一次性快照;股票 adj 比 raw 早结束(导出版本差异),见下 |
| **Yahoo(yfinance)** | 增量补到最新(已采用) | `auto_adjust=False` 给 raw + `Adj Close` | **30 分钟只回溯 60 天** | 无需登录;盘前盘后量=0;优先股代码不全;见下 |
| **IBKR(ib_async)** | 备选(更全、可 1 分钟) | `TRADES`=raw / `ADJUSTED_LAST`=adj | 深 | 需 TWS/Gateway 登录;**60 请求/10 分钟**硬限流(全宇宙 ~39h);本会话登录失败,脚本未在真账号验证 |

### 2. 原始供应商数据的"版本差异"坑(重要)
- 股票:**raw 到 2026-05-19**,但 **adj 只到 2026-04-13**(`YYYY(1).zip` 是更早导出)。
- ETF:raw 与 adj 都到 2026-04-13。
- 后果:股票 04-14→05-19 这段**有 raw、无 adj**。指标基于 adj,这段会断。
- 解法:① Yahoo 把数据补到最新(05-20→06-03);② `fill_adj_gap.py` 把中间 04-14→05-19 的 `adj := raw`(该窗口内基本无拆股/分红,且 adj 在 04-13 锚点处 = raw,所以等价)。回填后复权序列 2000→今连续。

### 3. Yahoo 刷新机制(`yahoo_fetch.py` + `yahoo_monitor.py`)
- `auto_adjust=False` → `Open/High/Low/Close`=未复权,`Adj Close`=复权;`adj_*` 用因子 `AdjClose/Close` 还原。
- 索引是**美东时区**;转 UTC 当 `ts`,去 tz 当 `et_time`(与全管线一致)。
- `prepost=1` 含 04:00–20:00;**盘前盘后成交量 = 0/不可靠**(指标只用 RTH,影响小)。
- 成交量是**真实股数**(不是 IBKR 的"手"×100)。
- 取一个统一窗口 `--period 58d`(稳在 60 天硬上限内),合并时按 ts 去重→只追加更新的 bar。
- **append-only 合并**:保留全部现有 bar,只补 ts 比现有最新更晚的;不覆盖历史、不回填(回填用 `fill_adj_gap.py`)。
- 监控:`yahoo_monitor.py [--watch 15]` 实时显示 ok/empty/error,把失败写 `yahoo_staging/_failures.txt`。

#### Yahoo 三个坑
1. **30 分钟只回溯 60 天**:`period=90d` 直接报 "must be within the last 60 days"。所以 ETF(停在 04-14、gap ~51 天)要**尽早跑**,超 60 天就补不了 30 分钟了。
2. **`period=58d` 对某些标的被解析成 ~69 天 > 60 而假报错**:用更小窗口(如 `--period 25d`)重取可救回(本会话救回 16 只被误判为退市的活跃股)。
3. **盘前盘后量=0**:导致 volume ratio 中位数=0(全是盘前盘后行),RTH 段价量正常。

### 4. 符号格式差异(各源不一样!)
| 含义 | 本数据集 | Yahoo | NASDAQ ACT | NASDAQ Symbol |
|---|---|---|---|---|
| 普通双类股 | `BRK.B` | `BRK-B` | `BRK.B` | `BRK-B` |
| 优先股 | `USB.R` | `USB-R`(常查不到) | `USB$R` | `USB-R` |
| Windows 保留名 | `PRN`→文件 `PRN_.parquet` | `PRN` | — | — |
- 脚本里:`yahoo_fetch.to_yahoo()` 把 `.`→`-` 且反解保留名(`PRN_`→`PRN`);`filter_common_stock.norm()` 把 `. $ -` 归一化后匹配 NASDAQ 名录。
- **Windows 保留名**:`CON/PRN/AUX/NUL/COM0-9/LPT0-9` 不能做文件名,`export_by_symbol.safe_filename()` 给它们加下划线(仅 `PRN`→`PRN_.parquet` 受影响)。

### 5. 宇宙过滤的两道闸(为什么是 6,300)
1. **流动性**(`liquidity_profile.py` + `build_universe.py`):
   - 股票:2026 末价 ≥ $1 **且** ADDV(自 2025-06-01 的平均日成交额)≥ $1M → 7,182 活跃 → 4,318。
   - ETF:ADDV ≥ $1M(无价格闸,ADDV 当 AUM 代理)→ 4,422 活跃 → 2,136。
2. **证券类型**(`filter_common_stock.py`,用 NASDAQ 官方名录的 `Security Name` 字段):
   - 剔除:优先股(80)、SPAC 单位(28)、baby-bond 债(16)、权证(2)+ 手动 C.K/APADU = 128 → 股票 4,318→4,190。
   - **保留**:双类普通股(BRK.B/HEI.A)、外国 ADR(RLX/KOF)、优先股**基金**(FFC,可交易普通份额)、LP 单位(IEP)。
   - 用户选择**保留**混入股票宇宙的 20 个 ETF(NASDAQ 标记为 ETF 但在股票 CSV 里)。
   - 分类要点:**"Depositary Shares"(非 American)= 美国优先股 → 删;"American Depositary"= 外国 ADR → 留**;名称常被截断/缩写(`Dep Shs`/`Prd`),带点代码 + 含 series/%/cumulative ⇒ 优先股。
3. **退市**(`prune_delisted.py`):补完仍到不了最新(last_ts 落后 >7 天)→ 移走。股票 4,190→4,167,ETF 2,136→2,133。

### 6. 已知遗留 / 注意
- `stock_delisted/` 里有几只**可能仍活跃但 Yahoo 无近期数据**的(APLS/SNCY/CSGS/TPH/MCW/AMWD/CVGW/VRE)——以后可用 IBKR 单独补,从该目录移回 `by_symbol/stock/` 即可。
- `features_daily/_stale/` 是 prune 后过期的日线(对应已剔除符号),可删。
- `parquet_smoketest/` 是早期小样测试输出,可删。

---

## English

### 1. Three sources
| Source | Use | Adjustment | Depth | Limits / gotchas |
|---|---|---|---|---|
| **Vendor zips/dirs** | initial full load (2000–2026) | raw + adj in separate files | full | one-shot; stock adj ends earlier than raw (export vintage) |
| **Yahoo (yfinance)** | incremental to latest (in use) | `auto_adjust=False` → raw + `Adj Close` | **30-min only last 60 days** | no login; pre/post volume=0; preferred tickers spotty |
| **IBKR (ib_async)** | alternative (fuller, 1-min) | `TRADES`=raw / `ADJUSTED_LAST`=adj | deep | needs TWS/Gateway; **60 req/10min** cap (~39h full); login failed this session, untested live |

### 2. Vendor "export-vintage" gap (important)
Stock **raw → 2026-05-19** but **adj → 2026-04-13**; ETFs both → 04-14. So stocks have raw-but-no-adj for
04-14→05-19, breaking adj-based indicators there. Fix: Yahoo extends to latest (05-20→06-03), and
`fill_adj_gap.py` sets `adj := raw` for the 04-14→05-19 hole (valid: adj==raw at the 04-13 anchor and
~no corporate action in the window). After that the adjusted series is continuous 2000→now.

### 3. Yahoo refresh (`yahoo_fetch.py` + `yahoo_monitor.py`)
`auto_adjust=False` → unadjusted OHLC + `Adj Close` (adj_* via factor `AdjClose/Close`). Index is ET →
UTC `ts` + naive ET `et_time`. `prepost=1` keeps 04:00–20:00 but **pre/post volume is 0/unreliable**.
Volume is **real shares**. Uses one uniform `--period 58d` window; **append-only merge** adds only bars
newer than each file's last ts (no overwrite, no backfill). Monitor with `yahoo_monitor.py [--watch 15]`.

**Yahoo gotchas:** (1) 30-min limited to last **60 days** — run soon; (2) `period=58d` is sometimes
expanded past 60 days and spuriously fails — retry with `--period 25d` (recovered 16 wrongly-flagged
actives this session); (3) pre/post volume = 0.

### 4. Symbol-format differences
Dual-class: dataset `BRK.B`, Yahoo `BRK-B`, NASDAQ ACT `BRK.B`. Preferred: dataset `USB.R`, Yahoo
`USB-R` (often missing), NASDAQ ACT `USB$R`. Reserved name: `PRN` → file `PRN_.parquet`. Scripts handle
this: `yahoo_fetch.to_yahoo()` (`.`→`-` + un-reserve), `filter_common_stock.norm()` (normalize `. $ -`),
`export_by_symbol.safe_filename()` (append `_` to CON/PRN/AUX/NUL/COM#/LPT#).

### 5. Two universe filters (why 6,300)
1. **Liquidity** (`liquidity_profile.py` + `build_universe.py`): stocks = 2026 last price ≥ $1 AND ADDV ≥ $1M
   (7,182→4,318); ETFs = ADDV ≥ $1M (4,422→2,136).
2. **Security type** (`filter_common_stock.py`, NASDAQ `Security Name`): drop 80 preferred + 28 SPAC units +
   16 baby-bond notes + 2 warrants + manual C.K/APADU = 128 (4,318→4,190). Keep dual-class common, foreign
   ADRs, preferred-income *funds*, LP units; user kept 20 mislabeled ETFs. Rule: domestic "Depositary Shares"
   = US preferred → drop; "American Depositary" = ADR → keep.
3. **Delisting** (`prune_delisted.py`): last_ts > 7 days stale after merge → moved out. Stocks 4,190→4,167,
   ETFs 2,136→2,133.

### 6. Known residual / notes
- `stock_delisted/` holds a few possibly-active names Yahoo lacks recent data for (APLS/SNCY/CSGS/TPH/MCW/
  AMWD/CVGW/VRE) — recover via IBKR later by moving back to `by_symbol/stock/`.
- `features_daily/_stale/` = post-prune stale daily files (removable). `parquet_smoketest/` = old smoke output (removable).
