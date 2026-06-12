-- ─────────────────────────────────────────────────────────────────────────────
-- COMPATIBILITY VIEWS  —  app/ML names → real data model (instruments/bars_*)
-- ─────────────────────────────────────────────────────────────────────────────
--
-- The backend, ML inference and (historically) the trainer query
-- market_data_30min / market_data_daily / indicators_30min. The real data lives
-- in bars_30m / bars_1d / instruments (loaded from data/30min_data + data/daily_data).
-- These views bridge the two so no app code needs the physical column layout.
--
-- Convention: prices are the SPLIT+DIVIDEND-ADJUSTED series (adj_*), so the app's
-- "adjusted = TRUE" filter is always satisfied. RTH rows only (matches training).

-- Drop the legacy empty base tables if they were created by an older 02_timeseries
-- (idempotent + type-safe: handles both table→view and re-running this file).
DO $$
DECLARE n TEXT;
BEGIN
  FOREACH n IN ARRAY ARRAY['market_data_30min', 'market_data_daily', 'indicators_30min'] LOOP
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
               WHERE c.relname = n AND s.nspname = 'public' AND c.relkind = 'r') THEN
      EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', n);
    END IF;
  END LOOP;
END $$;

-- ── market_data_30min ── OHLCV the candles endpoint + signal_engine expect ───
CREATE OR REPLACE VIEW market_data_30min AS
SELECT
    b.ts          AS time,
    i.symbol      AS ticker,
    b.adj_open    AS open,
    b.adj_high    AS high,
    b.adj_low     AS low,
    b.adj_close   AS close,
    b.adj_volume  AS volume,
    b.vwap_day    AS vwap,
    TRUE          AS adjusted,
    'import'::text AS source
FROM bars_30m b
JOIN instruments i ON i.instrument_id = b.instrument_id
WHERE b.rth;

-- ── market_data_10min ── 10-min OHLCV for the 1W chart range (over bars_10m) ──
CREATE OR REPLACE VIEW market_data_10min AS
SELECT
    b.ts          AS time,
    i.symbol      AS ticker,
    b.adj_open    AS open,
    b.adj_high    AS high,
    b.adj_low     AS low,
    b.adj_close   AS close,
    b.adj_volume  AS volume,
    b.vwap_day    AS vwap,
    TRUE          AS adjusted,
    'import'::text AS source
FROM bars_10m b
JOIN instruments i ON i.instrument_id = b.instrument_id
WHERE b.rth;

-- ── market_data_daily ── daily OHLCV for macro context / charting ────────────
CREATE OR REPLACE VIEW market_data_daily AS
SELECT
    b.ts          AS time,
    i.symbol      AS ticker,
    b.adj_open    AS open,
    b.adj_high    AS high,
    b.adj_low     AS low,
    b.adj_close   AS close,
    b.adj_volume  AS volume,
    b.adj_close   AS adjusted_close,
    'import'::text AS source
FROM bars_1d b
JOIN instruments i ON i.instrument_id = b.instrument_id;

-- ── indicators_30min ── model-ready features (must match xgboost_trainer.FEATURE_COLS) ─
-- Raw precomputed indicators are exposed verbatim; scale-free features that the
-- model consumes (atr_14_pct, price_vs_*, vwap_pct) are derived row-wise here so
-- training (DuckDB over the same parquet) and serving (this view) stay identical.
CREATE OR REPLACE VIEW indicators_30min AS
SELECT
    b.ts          AS time,
    i.symbol      AS ticker,
    b.rsi_14,
    b.macd,
    b.macd_signal,
    b.macd_hist,
    b.bb_pctb                                   AS bb_pct_b,
    b.bb_bw                                     AS bb_width,
    b.atr_14   / NULLIF(b.adj_close, 0)         AS atr_14_pct,
    b.adj_close / NULLIF(b.sma_200, 0) - 1      AS price_vs_sma200,
    b.adj_close / NULLIF(b.ema_50, 0)  - 1      AS price_vs_ema50,
    (b.adj_close - b.vwap_day) / NULLIF(b.vwap_day, 0) AS vwap_pct,
    b.ret_1bar,
    -- handy passthroughs for ad-hoc analysis (not model features)
    b.obv, b.sma_200, b.ema_50, b.atr_14, b.vwap_day
FROM bars_30m b
JOIN instruments i ON i.instrument_id = b.instrument_id
WHERE b.rth;

-- ── Convenience wide views (parity with data/docs/03) ────────────────────────
CREATE OR REPLACE VIEW v_bars_30m AS
SELECT i.symbol, i.asset_type, b.ts AT TIME ZONE 'America/New_York' AS et_time, b.*
FROM bars_30m b JOIN instruments i ON i.instrument_id = b.instrument_id;

CREATE OR REPLACE VIEW v_bars_1d AS
SELECT i.symbol, i.asset_type, b.ts AT TIME ZONE 'America/New_York' AS et_time, b.*
FROM bars_1d b JOIN instruments i ON i.instrument_id = b.instrument_id;
