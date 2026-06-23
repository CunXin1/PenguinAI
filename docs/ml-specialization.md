# ML Specialization — Per-Basket, Multi-Horizon Models

Status of roadmap B1/B2 (`docs/roadmap.md`) and the signal-confidence work.

## English

### 1. What changed and why

The product started with **one global XGBoost + one global Random Forest**, pooled
over all symbols, predicting a single binary target ("will adj_close be higher 16
30-min bars from now?"). Two problems surfaced:

1. **CV leakage** made the models look better than they are.
2. **Top-Signal confidences clustered at ~50%** — most signals were NEUTRAL @ 0.50.

Both are now understood and partly addressed. Single-stock models were considered and
**rejected** (they overfit — a liquid name has only ~16k 30-min bars, and price
direction has a very low signal-to-noise ratio). Instead we specialize by **curated
basket × horizon**.

### 2. Purged walk-forward CV (leakage fix)

`ml/models/xgboost_trainer.py` previously used sklearn `TimeSeriesSplit` on the pooled
feature matrix. Two leaks:

- The pooled multi-symbol rows were **not globally time-sorted** (no `ORDER BY`), so a
  position-based split did not respect time at all.
- The label is `LEAD(adj_close, horizon)`, so adjacent rows have **overlapping forward
  windows**; without an embargo, train rows at a fold boundary peek into the validation
  block.

Fix: `load_training_data` now selects `ts` and `label_end_ts = LEAD(ts, horizon)` and
`ORDER BY ts`; `purged_walk_forward_splits(cv_meta, n_splits)` cuts the timeline into
contiguous blocks and **drops every train row whose `label_end_ts` reaches the
validation block's start**. Verified: 0 leakage rows across all folds. Both trainers
(`xgboost_trainer`, `rf_trainer`) use it. The honest, leakage-free AUC for short-horizon
direction is ~0.50 — see section 5.

### 3. Stored-precision policy (separate cleanup)

All bar/indicator values are now rounded by category at compute/ingest time and a
one-time DB backfill (`backend/scripts/market_data/round_existing_precision.py`):

- Prices and price-derived indicators (OHLC, SMA/EMA, MACD family, Bollinger bands,
  ATR, VWAP) and all ratios/returns -> **4 decimals**.
- `rsi_14` (0-100 oscillator) -> **2 decimals**.
- `obv` (cumulative volume) -> **0 decimals**.

Single source of truth: `compute_indicators.ROUND_DECIMALS`. Note this does NOT save
storage (DOUBLE PRECISION is fixed 8 bytes); it only standardizes the stored decimals.

### 4. Basket × horizon model grid

A **basket** is a curated ticker list whose members share dynamics; one model is trained
on the pooled rows of all members per (timeframe, horizon). This gives far more data than
a single-stock model while staying more specialized than the global model. Config:
`ml/models/baskets.py` (`nasdaq10` now; `smallcap` / `wholemarket` planned).

Match bar granularity to the horizon band it has the data to support:

| Horizon | Source | Bars ahead | Target | Notes |
|---------|--------|-----------|--------|-------|
| 1 week  | `data/30min_data` (`bars_30m`) | 65 | direction (up/down) | workhorse; most data |
| 1 month | `data/daily_data` (`bars_1d`) | 21 | **beat_spy** (excess vs SPY) | — |
| 3 months| `data/daily_data` (`bars_1d`) | 63 | **beat_spy** | strongest real edge |
| 1 day   | 1-min / aggregated 10-min | TBD | direction | deferred — pending 1-min/10-min data |

Why `beat_spy` for the 1m/3m tiers: over months the market drifts up, so "will it be
higher?" is ~55-65% yes always and the classifier degenerates to "always up". Predicting
**"will this symbol's forward return beat SPY's over the same window?"** removes the
drift (target balance becomes ~0.50-0.58) and isolates real alpha. 6-month / 1-year
tiers are intentionally **not** built: daily history is only ~5 years, so those horizons
have too few independent windows.

Feature sets: 30m reuses the 11 `FEATURE_SQL` columns (parity with `indicators_30min`);
1d uses `DAILY_FEATURE_SQL` (same technical core minus intraday-only VWAP/ret_1bar, plus
1- and 3-month momentum `ret_21d`/`ret_63d`). The SPY-relative target joins SPY forward
returns in DuckDB.

Artifacts are keyed `{basket}__{timeframe}__{label}__{algo}.pkl` (e.g.
`nasdaq10__1d__3m__xgb.pkl`) under `MODEL_DIR`. Train via
`python -m ml.scripts.train_basket_models --basket nasdaq10`.

### 5. Results (purged walk-forward CV AUC, nasdaq10, 2021-)

| Horizon | XGB | RF | Samples |
|---------|-----|----|---------|
| 1 week (direction) | 0.499 | 0.491 | 160,634 |
| 1 month (beat_spy) | 0.527 | 0.496 | 12,235 |
| 3 months (beat_spy)| **0.562** | 0.509 | 11,815 |

Read honestly: 1-week direction on mega-caps is ~coin-flip (matches the global model's
0.516). The **3-month beat-SPY model carries a real, if modest, edge**. XGB beats RF
throughout. These are indicative on ~10 symbols / 5 years; they firm up with the full
universe and longer history.

### 6. The 50%-confidence-clustering diagnosis

Measured on the live `signal_cache` (computed by the old global model): 47/64 signals
were NEUTRAL @ ~0.508; `ensemble_prob` mean 0.484, **stddev only 0.068**. The
probabilities themselves cluster at 0.5, and the confidence map
`abs(p-0.5)*4+0.5` then collapses everything to ~0.50.

Crucial: the leakage fix does **not** decluster this — it makes short-horizon
probabilities even more honestly near 0.5. Inflating confidence artificially would be
dishonest. The real fix is twofold:

1. Take signals from horizons/targets that carry real signal (3-month beat-SPY).
2. Have the Gemma agent **synthesize** many weak-but-independent sources into one
   signal — ML across all horizons (1w/1m/3m) + FinBERT news/sentiment + technical
   indicators + price/volume + earnings + FOMC/macro — with confidence reflecting
   cross-source agreement, not any single near-0.5 probability.

**Built (B-synthesis).** The keyed horizon models are now wired into the signal path:

- `model_registry.predict_basket_horizons(ticker, feats_by_tf)` resolves the ticker's
  basket (`baskets.basket_for`) and returns `{1w: P(up), 1m: P(beat SPY), 3m: P(beat SPY)}`,
  each model predicted via its OWN saved `feature_names_in_`. Empty for non-basket tickers.
- `signal_engine` loads daily features from the new `indicators_daily` view (mirrors
  `DAILY_FEATURE_SQL`) and passes the horizons to `gemma_agent`.
- `gemma_agent` synthesizes ALL horizons + FinBERT + macro into ONE direction with a
  narrowed band (LONG ≥0.52 / SHORT ≤0.48; NEUTRAL only on genuine cross-horizon
  conflict) and confidence = cross-horizon/cross-source AGREEMENT. The ML-only fallback
  averages the same horizon probs and sets confidence from the agreement fraction.
- Non-basket tickers (e.g. SPY/QQQ) keep the global-ensemble path unchanged.

Why this de-NEUTRALs the homepage: the 9 defaults are mega-caps whose 1-week prob sits
in the 0.50–0.55 dead zone (all → NEUTRAL under the old 0.55 bar), but their 1m/3m
beat-SPY models carry real signal (e.g. AAPL 1w≈0.51 but 1m≈0.68), so synthesis produces
a decisive, honestly-confident call. Confidence is no longer surfaced in the frontend (a
high-confidence NEUTRAL read as a contradiction to users); it remains in the API/cache.

### 7. Files

```
ml/models/xgboost_trainer.py     purged_walk_forward_splits, load_training_data(timeframe,target_type), DAILY_FEATURE_SQL
ml/models/rf_trainer.py          same CV + timeframe/target_type
ml/models/baskets.py             BASKETS (nasdaq10), basket_for()
ml/scripts/train_basket_models.py  driver: train basket x {1w,1m,3m} x {xgb,rf}
backend/scripts/market_data/round_existing_precision.py   one-time precision backfill
```

## 中文

### 1. 改了什么、为什么

产品起初是**一个全局 XGBoost + 一个全局随机森林**，把所有股票 pool 在一起，预测单一
二分类目标（「16 根 30 分钟 bar 后 adj_close 是否更高」）。暴露两个问题：

1. **CV 泄漏**让模型看着比实际能打。
2. **Top Signal 的 confidence 全挤在 ~50%** —— 大多数是 NEUTRAL @ 0.50。

两者现在都搞清楚了、部分已解决。单股模型评估后**否决**（过拟合 —— 一只流动性股也就
~1.6 万根 30 分钟 bar，而价格方向信噪比极低）。改为按**精选篮子 × 时间跨度**专门化。

### 2. Purged walk-forward CV（泄漏修复）

`ml/models/xgboost_trainer.py` 原先在 pool 后的特征矩阵上用 sklearn `TimeSeriesSplit`，
两处泄漏：

- pool 的多 symbol 行**没有全局按时间排序**（无 `ORDER BY`），按行号切根本不尊重时间。
- 标签是 `LEAD(adj_close, horizon)`，相邻行的**未来窗口重叠**；没有 embargo，fold 边界
  的训练行会探进验证集。

修复：`load_training_data` 现在选出 `ts` 和 `label_end_ts = LEAD(ts, horizon)` 并
`ORDER BY ts`；`purged_walk_forward_splits` 把时间轴切成连续块，并**剔除所有
`label_end_ts` 触及验证块起点的训练行**。已验证：所有 fold 0 泄漏。两个 trainer 都用它。
短跨度方向的无泄漏真实 AUC ≈ 0.50 —— 见第 5 节。

### 3. 存储精度策略（独立清理）

所有 bar/指标值现在在计算/ingest 时按类别 round，并有一次性 DB backfill
（`backend/scripts/market_data/round_existing_precision.py`）：

- 价格及价格量纲指标（OHLC、SMA/EMA、MACD 家族、布林带、ATR、VWAP）和所有比率/收益率
  -> **4 位**。
- `rsi_14`（0-100 振荡器）-> **2 位**。
- `obv`（累积成交量）-> **整数**。

单一事实源：`compute_indicators.ROUND_DECIMALS`。注意这**不省存储**（DOUBLE PRECISION
恒为 8 字节），只是统一了小数位。

### 4. 篮子 × 跨度 网格

**篮子**是一组动态相近的精选股票；每个 (timeframe, horizon) 组合用篮子全体成员的 pool
行训练一个模型。比单股数据多得多，又比全局模型更专门。配置在 `ml/models/baskets.py`
（现有 `nasdaq10`；规划中 `smallcap` / `wholemarket`）。

让 bar 粒度匹配它数据撑得住的跨度带：

| 跨度 | 源 | 往前 bar | 目标 | 备注 |
|------|----|---------|------|------|
| 1 周 | `data/30min_data`（`bars_30m`） | 65 | 涨/跌 | 主力，数据最多 |
| 1 月 | `data/daily_data`（`bars_1d`） | 21 | **beat_spy**（超额 vs SPY） | — |
| 3 月 | `data/daily_data`（`bars_1d`） | 63 | **beat_spy** | 真实 edge 最强 |
| 1 天 | 1min / 聚合 10min | 待定 | 涨/跌 | 暂缓 —— 等 1min/10min 数据 |

1月/3月用 `beat_spy` 的原因：长跨度里大盘长期上行，「是否更高」常年 55-65% 是 yes，
分类器退化成「永远猜涨」。改预测**「该股 forward 收益是否跑赢 SPY」**去掉漂移
（目标占比回到 ~0.50-0.58），分离出真正的 alpha。6 月/1 年档**故意不做**：日线只有
~5 年，独立窗口太少。

特征集：30m 复用 11 个 `FEATURE_SQL` 列（与 `indicators_30min` 一致）；1d 用
`DAILY_FEATURE_SQL`（同款技术核心，去掉日内 VWAP/ret_1bar，加 1/3 月动量
`ret_21d`/`ret_63d`）。超额目标在 DuckDB 里 join SPY 的 forward 收益。

模型键 `{basket}__{timeframe}__{label}__{algo}.pkl`（如 `nasdaq10__1d__3m__xgb.pkl`），
存于 `MODEL_DIR`。训练：`python -m ml.scripts.train_basket_models --basket nasdaq10`。

### 5. 结果（purged walk-forward CV AUC，nasdaq10，2021-）

| 跨度 | XGB | RF | 样本 |
|------|-----|----|----|
| 1 周（方向） | 0.499 | 0.491 | 160,634 |
| 1 月（beat_spy） | 0.527 | 0.496 | 12,235 |
| 3 月（beat_spy）| **0.562** | 0.509 | 11,815 |

诚实地读：巨头股 1 周方向 ≈ 抛硬币（与全局 0.516 一致）。**3 月 beat-SPY 有真实但温和
的 edge**。XGB 全面优于 RF。这是 ~10 股 / 5 年的指示性结果，完整 universe + 更长历史会
更稳。

### 6. 50% confidence 聚集的诊断

在线上 `signal_cache`（旧全局模型算的）上实测：64 条里 47 条 NEUTRAL @ ~0.508；
`ensemble_prob` 均值 0.484、**标准差仅 0.068**。概率本身就贴 0.5，confidence 映射
`abs(p-0.5)*4+0.5` 把一切压回 ~0.50。

关键：修 leakage **不会**解决聚集 —— 它让短跨度概率更老实地贴近 0.5。硬拉高 confidence
是骗人。真正的解法有两条：

1. 去有真信号的跨度/目标取信号（3 月 beat-SPY）。
2. 让 Gemma agent 把多个弱但独立的源**综合**成一个信号 —— 全跨度 ML(1周/1月/3月) +
   FinBERT 新闻/情绪 + 技术指标 + 价量 + 财报 + FOMC/宏观 —— confidence 反映各源是否
   一致，而非单个贴近 0.5 的概率。

这是下一步构建（B-综合）：把 keyed horizon 模型喂进 `signal_engine`/`gemma_agent`，并把
confidence 重新标定为跨跨度与跨源的一致性。同一份多跨度预测也支撑前端的跨度切换器。

### 7. 文件

```
ml/models/xgboost_trainer.py     purged_walk_forward_splits、load_training_data(timeframe,target_type)、DAILY_FEATURE_SQL
ml/models/rf_trainer.py          同款 CV + timeframe/target_type
ml/models/baskets.py             BASKETS(nasdaq10)、basket_for()
ml/scripts/train_basket_models.py  driver：训练 篮子 x {1w,1m,3m} x {xgb,rf}
backend/scripts/market_data/round_existing_precision.py   一次性精度 backfill
```
