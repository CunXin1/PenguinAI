CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS instruments (
  instrument_id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'etf')),
  first_ts TIMESTAMPTZ,
  last_ts TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (symbol, asset_type)
);

CREATE TABLE IF NOT EXISTS bars_30m (
  ts TIMESTAMPTZ NOT NULL,
  instrument_id BIGINT NOT NULL REFERENCES instruments(instrument_id),
  raw_open DOUBLE PRECISION,
  raw_high DOUBLE PRECISION,
  raw_low DOUBLE PRECISION,
  raw_close DOUBLE PRECISION,
  raw_volume BIGINT,
  adj_open DOUBLE PRECISION,
  adj_high DOUBLE PRECISION,
  adj_low DOUBLE PRECISION,
  adj_close DOUBLE PRECISION,
  adj_volume BIGINT,
  inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ts, instrument_id),
  CHECK (
    raw_open IS NOT NULL
    OR raw_high IS NOT NULL
    OR raw_low IS NOT NULL
    OR raw_close IS NOT NULL
    OR raw_volume IS NOT NULL
    OR adj_open IS NOT NULL
    OR adj_high IS NOT NULL
    OR adj_low IS NOT NULL
    OR adj_close IS NOT NULL
    OR adj_volume IS NOT NULL
  )
);

SELECT create_hypertable(
  'bars_30m',
  by_range('ts', INTERVAL '1 month'),
  if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS bars_30m_instrument_ts_desc_idx
  ON bars_30m (instrument_id, ts DESC);

CREATE INDEX IF NOT EXISTS bars_30m_ts_desc_idx
  ON bars_30m (ts DESC);

CREATE TABLE IF NOT EXISTS import_runs (
  import_run_id BIGSERIAL PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running',
  input_format TEXT,
  scope TEXT,
  years_filter TEXT,
  symbols_filter TEXT,
  files_planned INTEGER NOT NULL DEFAULT 0,
  files_seen INTEGER NOT NULL DEFAULT 0,
  rows_seen BIGINT NOT NULL DEFAULT 0,
  rows_loaded BIGINT NOT NULL DEFAULT 0,
  rows_invalid BIGINT NOT NULL DEFAULT 0,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS import_files (
  source_file TEXT PRIMARY KEY,
  symbol TEXT,
  asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'etf')),
  import_run_id BIGINT REFERENCES import_runs(import_run_id),
  rows_seen BIGINT NOT NULL DEFAULT 0,
  rows_valid BIGINT NOT NULL DEFAULT 0,
  rows_invalid BIGINT NOT NULL DEFAULT 0,
  first_ts TIMESTAMPTZ,
  last_ts TIMESTAMPTZ,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dataset_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO dataset_metadata (key, value)
VALUES
  ('bar_interval', '30 minutes'),
  ('source_timezone', 'America/New_York'),
  ('zero_volume_bars', 'omitted'),
  ('row_grain', 'one row per timestamp and instrument'),
  ('asset_types', 'stock, etf'),
  ('adjustment_layout', 'raw_* columns and adj_* columns'),
  ('price_storage', 'double precision'),
  ('volume_storage', 'bigint shares')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    updated_at = now();

CREATE OR REPLACE VIEW v_bars_30m AS
SELECT
  b.ts,
  b.ts AT TIME ZONE 'America/New_York' AS et_time,
  i.symbol,
  i.asset_type,
  b.raw_open,
  b.raw_high,
  b.raw_low,
  b.raw_close,
  b.raw_volume,
  b.adj_open,
  b.adj_high,
  b.adj_low,
  b.adj_close,
  b.adj_volume
FROM bars_30m b
JOIN instruments i ON i.instrument_id = b.instrument_id;

CREATE OR REPLACE VIEW v_bars_30m_long AS
SELECT
  ts,
  et_time,
  symbol,
  asset_type,
  'raw' AS adjustment,
  raw_open AS open,
  raw_high AS high,
  raw_low AS low,
  raw_close AS close,
  raw_volume AS volume
FROM v_bars_30m
WHERE raw_open IS NOT NULL
UNION ALL
SELECT
  ts,
  et_time,
  symbol,
  asset_type,
  'split_dividend_adjusted' AS adjustment,
  adj_open AS open,
  adj_high AS high,
  adj_low AS low,
  adj_close AS close,
  adj_volume AS volume
FROM v_bars_30m
WHERE adj_open IS NOT NULL;
