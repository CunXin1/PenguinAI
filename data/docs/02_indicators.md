# 02 · 指标计算 / Indicators

实现见 `scripts/compute_indicators.py`。两套产物用**同一套指标函数**:
- 30 分钟版 → 写回 `by_symbol/`(周期单位 = bar 数)
- 日线版 → 写到 `features_daily/`(周期单位 = 天)

Implementation: `scripts/compute_indicators.py`. The 30-min and daily outputs share the
**same indicator functions** (period = bars for 30-min, = days for daily).

---

## 中文

### 通用口径(很重要)
1. **价格一律用 `adj_*`(复权)** 算指标——否则拆股当天均线/RSI 会出假信号。`raw_*` 只用于真实成交价/成交额。
2. **只在正股时段(RTH, 09:30–16:00)算**:先把数据过滤到 RTH 连续序列再算;盘前盘后行指标为空。
3. **只在 `adj_close` 非空的行上算**:否则 `ewm`/`cumsum` 类指标(RSI/EMA/MACD/ATR/OBV)遇到 NaN 会**冻结沿用上一个值**,伪造出"当前信号"。缺 adj 的行得到诚实的 NaN。
4. 暖机期(如 SMA200 的前 200 根)为 NaN,属正常。

### A. 趋势 / 均线
- **SMA(简单移动平均)**,窗口 n∈{20,50,200}:
  `sma_n = mean(adj_close, 最近 n 根)`(`rolling(n).mean()`,不足 n 根为 NaN)
- **EMA(指数移动平均)**,span∈{12,26,50}:
  递归 `EMA_t = α·close_t + (1−α)·EMA_{t−1}`,`α = 2/(span+1)`(`ewm(span, adjust=False)`)
- **MACD(12/26/9)**:
  `macd = EMA12 − EMA26`;`macd_signal = EMA9(macd)`;`macd_hist = macd − macd_signal`

### B. 动量
- **RSI(14, Wilder)**:
  `Δ = diff(adj_close)`;`gain = max(Δ,0)`,`loss = max(−Δ,0)`;
  用 Wilder 平滑(`ewm(alpha=1/14, adjust=False)`)得 `avgGain`、`avgLoss`;
  `RS = avgGain / avgLoss`;`RSI = 100 − 100/(1+RS)`。范围 [0,100]。

### C. 波动率
- **布林带(20, 2σ)**:
  `bb_mid = SMA20`;`sd = rolling(20).std(ddof=0)`(总体标准差);
  `bb_upper = mid + 2sd`,`bb_lower = mid − 2sd`;
  `bb_pctb = (close − lower)/(upper − lower)`(价格在带内位置,>1 突破上轨);
  `bb_bw = (upper − lower)/mid`(带宽,衡量收缩/扩张)。
- **ATR(14, Wilder)**:
  真实波幅 `TR = max(H−L, |H−prevC|, |L−prevC|)`;`ATR = Wilder平滑(TR, 14)`。

### D. 量 / 价量
- **VWAP(日内,按交易日重置)** —— 仅 30 分钟版:
  典型价 `tp = (H+L+C)/3`;当日内 `vwap_day = cumsum(tp·vol)/cumsum(vol)`,**每个交易日清零重算**。
- **OBV(能量潮)**:
  `OBV_t = OBV_{t−1} + sign(Δclose)·volume`(累计有向成交量)。

### E. 收益
- **`ret_1bar`**(仅 30 分钟版):`adj_close.pct_change(1)`,相邻 bar 收益。
- **多周期日收益**(仅日线版):`ret_Nd = adj_close.pct_change(N)`,N∈{1,5,21,63,126,252}
  (≈ 1 日 / 1 周 / 1 月 / 1 季 / 半年 / 1 年)。
- **`gap_overnight`**(仅日线版):`今日 adj_open / 昨日 adj_close − 1`。

### 实现注意点
- Wilder 平滑用 `ewm(alpha=1/14, adjust=False)` 近似(种子用首值,~100 根后与经典 Wilder 收敛)。
- 布林带用**总体标准差 ddof=0**(布林原版口径)。
- VWAP 用 `et_time` 的日期分组(`groupby(交易日).cumsum()`)。
- 30 分钟"1 天 ≈ 13 根",但半日市更少;所以"按天"的收益放在**日线版**(精确按交易日),不用 bar 数硬换算。

### 还没做(可作第二批)
- 横截面类:对 SPY 的滚动 beta/相关/残差波动、横截面排名/z-score(需所有标的按时间对齐 + 大盘基准)。
- 其他:ADX/DMI、Stochastic、CCI、ROC、MFI、CMF/ADL、Keltner、Realized Vol、VWMA 等(列表见会话记录)。

---

## English

### Universal conventions (important)
1. **Use `adj_*` (adjusted) for all indicators** — otherwise MAs/RSI jump on split days. `raw_*` is only for true price/dollar-volume.
2. **Compute on RTH only (09:30–16:00)**: filter to a contiguous RTH series first; extended-hours rows get NULL indicators.
3. **Compute only where `adj_close` is non-null**: otherwise `ewm`/`cumsum` indicators (RSI/EMA/MACD/ATR/OBV) carry the last value forward over NaNs, faking a "current" signal. Missing-adj rows get honest NaN.
4. Warmup (e.g. first 200 bars for SMA200) is NaN — expected.

### A. Trend / moving averages
- **SMA**, n∈{20,50,200}: `rolling(n).mean()` of adj_close (NaN until n bars).
- **EMA**, span∈{12,26,50}: `ewm(span, adjust=False)`, `α = 2/(span+1)`.
- **MACD(12/26/9)**: `macd = EMA12 − EMA26`; `macd_signal = EMA9(macd)`; `macd_hist = macd − macd_signal`.

### B. Momentum
- **RSI(14, Wilder)**: `Δ = diff(close)`; `gain=max(Δ,0)`, `loss=max(−Δ,0)`; Wilder-smooth via
  `ewm(alpha=1/14, adjust=False)` → `avgGain/avgLoss`; `RS = avgGain/avgLoss`; `RSI = 100 − 100/(1+RS)`. Range [0,100].

### C. Volatility
- **Bollinger(20, 2σ)**: `bb_mid = SMA20`; `sd = rolling(20).std(ddof=0)` (population);
  `bb_upper/lower = mid ± 2sd`; `bb_pctb = (close−lower)/(upper−lower)`; `bb_bw = (upper−lower)/mid`.
- **ATR(14, Wilder)**: `TR = max(H−L, |H−prevC|, |L−prevC|)`; `ATR = Wilder-smooth(TR,14)`.

### D. Volume / price-volume
- **VWAP (intraday, reset per trading day)** — 30-min only: `tp=(H+L+C)/3`;
  `vwap_day = cumsum(tp·vol)/cumsum(vol)` grouped by ET date.
- **OBV**: `OBV_t = OBV_{t−1} + sign(Δclose)·volume`.

### E. Returns
- **`ret_1bar`** (30-min): `pct_change(1)` of adj_close.
- **Multi-horizon daily returns** (daily): `ret_Nd = pct_change(N)`, N∈{1,5,21,63,126,252}.
- **`gap_overnight`** (daily): `today adj_open / yesterday adj_close − 1`.

### Implementation notes
- Wilder smoothing approximated by `ewm(alpha=1/14, adjust=False)` (seeds on first value; converges to classic Wilder after ~100 bars).
- Bollinger uses **population std (ddof=0)** (original Bollinger convention).
- VWAP groups by the `et_time` date.
- "1 day ≈ 13 bars" intraday is inexact (half-days); day-horizon returns live in the **daily** output (exact trading-day grouping).

### Not yet built (batch 2 candidates)
- Cross-sectional: rolling beta/corr vs SPY + idiosyncratic vol, cross-sectional rank/z-score (need all symbols time-aligned + SPY benchmark).
- Others: ADX/DMI, Stochastic, CCI, ROC, MFI, CMF/ADL, Keltner, Realized Vol, VWMA (full list in the session log).
