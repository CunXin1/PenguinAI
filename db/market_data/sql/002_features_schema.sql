-- Per-timeframe hypertables WITH precomputed indicators, loaded from the cleaned
-- by_symbol (30-min) + features_daily (daily) parquet. Reuses instruments + the
-- import bookkeeping tables from 001_schema.sql; recreates bars_30m with indicator
-- columns and adds a new daily hypertable bars_1d.

DROP VIEW IF EXISTS v_bars_30m_long;
DROP VIEW IF EXISTS v_bars_30m;
DROP VIEW IF EXISTS v_bars_1d;
DROP TABLE IF EXISTS bars_30m CASCADE;
DROP TABLE IF EXISTS bars_1d CASCADE;

TRUNCATE instruments RESTART IDENTITY CASCADE;

-- 30-minute bars + indicators (price indicators on adj_*, RTH session only) -------
CREATE TABLE bars_30m (
  ts TIMESTAMPTZ NOT NULL,
  instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
  rth BOOLEAN,
  raw_open DOUBLE PRECISION, raw_high DOUBLE PRECISION, raw_low DOUBLE PRECISION,
  raw_close DOUBLE PRECISION, raw_volume BIGINT,
  adj_open DOUBLE PRECISION, adj_high DOUBLE PRECISION, adj_low DOUBLE PRECISION,
  adj_close DOUBLE PRECISION, adj_volume BIGINT,
  sma_20 DOUBLE PRECISION, sma_50 DOUBLE PRECISION, sma_200 DOUBLE PRECISION,
  ema_12 DOUBLE PRECISION, ema_26 DOUBLE PRECISION, ema_50 DOUBLE PRECISION,
  macd DOUBLE PRECISION, macd_signal DOUBLE PRECISION, macd_hist DOUBLE PRECISION,
  rsi_14 DOUBLE PRECISION,
  bb_mid DOUBLE PRECISION, bb_upper DOUBLE PRECISION, bb_lower DOUBLE PRECISION,
  bb_pctb DOUBLE PRECISION, bb_bw DOUBLE PRECISION,
  atr_14 DOUBLE PRECISION, obv DOUBLE PRECISION, vwap_day DOUBLE PRECISION,
  ret_1bar DOUBLE PRECISION,
  PRIMARY KEY (ts, instrument_id)
);
SELECT create_hypertable('bars_30m', by_range('ts', INTERVAL '1 month'), if_not_exists => TRUE);

-- Daily bars + indicators + multi-horizon returns -------------------------------
CREATE TABLE bars_1d (
  ts TIMESTAMPTZ NOT NULL,
  instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
  rth_bars INTEGER,
  raw_close DOUBLE PRECISION,
  adj_open DOUBLE PRECISION, adj_high DOUBLE PRECISION, adj_low DOUBLE PRECISION,
  adj_close DOUBLE PRECISION, adj_volume BIGINT,
  sma_20 DOUBLE PRECISION, sma_50 DOUBLE PRECISION, sma_200 DOUBLE PRECISION,
  ema_12 DOUBLE PRECISION, ema_26 DOUBLE PRECISION, ema_50 DOUBLE PRECISION,
  macd DOUBLE PRECISION, macd_signal DOUBLE PRECISION, macd_hist DOUBLE PRECISION,
  rsi_14 DOUBLE PRECISION,
  bb_mid DOUBLE PRECISION, bb_upper DOUBLE PRECISION, bb_lower DOUBLE PRECISION,
  bb_pctb DOUBLE PRECISION, bb_bw DOUBLE PRECISION,
  atr_14 DOUBLE PRECISION, obv DOUBLE PRECISION,
  ret_1d DOUBLE PRECISION, ret_5d DOUBLE PRECISION, ret_21d DOUBLE PRECISION,
  ret_63d DOUBLE PRECISION, ret_126d DOUBLE PRECISION, ret_252d DOUBLE PRECISION,
  gap_overnight DOUBLE PRECISION,
  PRIMARY KEY (ts, instrument_id)
);
SELECT create_hypertable('bars_1d', by_range('ts', INTERVAL '1 year'), if_not_exists => TRUE);

CREATE INDEX bars_30m_instrument_ts_desc_idx ON bars_30m (instrument_id, ts DESC);
CREATE INDEX bars_1d_instrument_ts_desc_idx  ON bars_1d  (instrument_id, ts DESC);

CREATE OR REPLACE VIEW v_bars_30m AS
SELECT i.symbol, i.asset_type, b.ts AT TIME ZONE 'America/New_York' AS et_time, b.*
FROM bars_30m b JOIN instruments i ON i.instrument_id = b.instrument_id;

CREATE OR REPLACE VIEW v_bars_1d AS
SELECT i.symbol, i.asset_type, b.ts AT TIME ZONE 'America/New_York' AS et_time, b.*
FROM bars_1d b JOIN instruments i ON i.instrument_id = b.instrument_id;

INSERT INTO dataset_metadata (key, value) VALUES ('schema_version', '002_features')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
