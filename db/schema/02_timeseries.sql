-- ─────────────────────────────────────────────────────────────────────────────
-- TIME-SERIES TABLES  (TimescaleDB Hypertables)
-- ─────────────────────────────────────────────────────────────────────────────
--
-- This file is the single source of truth for the market-data model. It mirrors
-- the data-pipeline schema that the parquet loader targets
-- (db/market_data/sql/002_features_schema.sql) so the real data under
-- data/30min_data/ + data/daily_data/ lands in THIS database (penguinai).
--
-- The app/ML code keeps querying the familiar names market_data_30min /
-- market_data_daily / indicators_30min — those are now COMPATIBILITY VIEWS over
-- the tables below (see 04_compat_views.sql). market_data_1min stays a real
-- forward-accumulating table (IBKR + Massive minute streams).

-- ── Instrument dimension (symbol ↔ instrument_id) ────────────────────────────
-- Populated by the parquet loader (db/market_data/import_features_to_timescale.py).
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id BIGSERIAL    PRIMARY KEY,
    symbol        TEXT         NOT NULL,
    asset_type    TEXT         NOT NULL CHECK (asset_type IN ('stock', 'etf')),
    first_ts      TIMESTAMPTZ,
    last_ts       TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (symbol, asset_type)
);

-- ── 30-minute bars + indicators (primary training source, 2000–present) ──────
-- raw_* = unadjusted, adj_* = split+dividend adjusted; indicators computed on
-- adj_* over RTH rows. Loaded RTH-only by default. One row per (ts, instrument).
CREATE TABLE IF NOT EXISTS bars_30m (
    ts            TIMESTAMPTZ      NOT NULL,
    instrument_id BIGINT           NOT NULL REFERENCES instruments(instrument_id),
    rth           BOOLEAN,
    raw_open      DOUBLE PRECISION, raw_high  DOUBLE PRECISION, raw_low DOUBLE PRECISION,
    raw_close     DOUBLE PRECISION, raw_volume BIGINT,
    adj_open      DOUBLE PRECISION, adj_high  DOUBLE PRECISION, adj_low DOUBLE PRECISION,
    adj_close     DOUBLE PRECISION, adj_volume BIGINT,
    -- Trend
    sma_20        DOUBLE PRECISION, sma_50    DOUBLE PRECISION, sma_200 DOUBLE PRECISION,
    ema_12        DOUBLE PRECISION, ema_26    DOUBLE PRECISION, ema_50  DOUBLE PRECISION,
    -- Momentum
    macd          DOUBLE PRECISION, macd_signal DOUBLE PRECISION, macd_hist DOUBLE PRECISION,
    rsi_14        DOUBLE PRECISION,
    -- Volatility (Bollinger + ATR)
    bb_mid        DOUBLE PRECISION, bb_upper  DOUBLE PRECISION, bb_lower DOUBLE PRECISION,
    bb_pctb       DOUBLE PRECISION, bb_bw     DOUBLE PRECISION,
    atr_14        DOUBLE PRECISION,
    -- Volume / intraday / returns
    obv           DOUBLE PRECISION, vwap_day  DOUBLE PRECISION,
    ret_1bar      DOUBLE PRECISION,
    PRIMARY KEY (ts, instrument_id)
);
SELECT create_hypertable('bars_30m', by_range('ts', INTERVAL '1 month'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS bars_30m_instrument_ts_desc_idx ON bars_30m (instrument_id, ts DESC);

-- ── Daily bars + indicators + multi-horizon returns (macro context) ──────────
CREATE TABLE IF NOT EXISTS bars_1d (
    ts            TIMESTAMPTZ      NOT NULL,   -- day's last RTH bar, UTC
    instrument_id BIGINT           NOT NULL REFERENCES instruments(instrument_id),
    rth_bars      INTEGER,
    raw_close     DOUBLE PRECISION,
    adj_open      DOUBLE PRECISION, adj_high  DOUBLE PRECISION, adj_low DOUBLE PRECISION,
    adj_close     DOUBLE PRECISION, adj_volume BIGINT,
    sma_20        DOUBLE PRECISION, sma_50    DOUBLE PRECISION, sma_200 DOUBLE PRECISION,
    ema_12        DOUBLE PRECISION, ema_26    DOUBLE PRECISION, ema_50  DOUBLE PRECISION,
    macd          DOUBLE PRECISION, macd_signal DOUBLE PRECISION, macd_hist DOUBLE PRECISION,
    rsi_14        DOUBLE PRECISION,
    bb_mid        DOUBLE PRECISION, bb_upper  DOUBLE PRECISION, bb_lower DOUBLE PRECISION,
    bb_pctb       DOUBLE PRECISION, bb_bw     DOUBLE PRECISION,
    atr_14        DOUBLE PRECISION, obv       DOUBLE PRECISION,
    ret_1d        DOUBLE PRECISION, ret_5d    DOUBLE PRECISION, ret_21d DOUBLE PRECISION,
    ret_63d       DOUBLE PRECISION, ret_126d  DOUBLE PRECISION, ret_252d DOUBLE PRECISION,
    gap_overnight DOUBLE PRECISION,
    PRIMARY KEY (ts, instrument_id)
);
SELECT create_hypertable('bars_1d', by_range('ts', INTERVAL '1 year'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS bars_1d_instrument_ts_desc_idx ON bars_1d (instrument_id, ts DESC);

-- ── Import bookkeeping (one row per load run / source file) ───────────────────
CREATE TABLE IF NOT EXISTS import_runs (
    import_run_id BIGSERIAL    PRIMARY KEY,
    started_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT         NOT NULL DEFAULT 'running',
    input_format  TEXT,
    scope         TEXT,
    years_filter  TEXT,
    symbols_filter TEXT,
    files_planned INTEGER      NOT NULL DEFAULT 0,
    files_seen    INTEGER      NOT NULL DEFAULT 0,
    rows_seen     BIGINT       NOT NULL DEFAULT 0,
    rows_loaded   BIGINT       NOT NULL DEFAULT 0,
    rows_invalid  BIGINT       NOT NULL DEFAULT 0,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS import_files (
    source_file   TEXT         PRIMARY KEY,
    symbol        TEXT,
    asset_type    TEXT         NOT NULL CHECK (asset_type IN ('stock', 'etf')),
    import_run_id BIGINT       REFERENCES import_runs(import_run_id),
    rows_seen     BIGINT       NOT NULL DEFAULT 0,
    rows_valid    BIGINT       NOT NULL DEFAULT 0,
    rows_invalid  BIGINT       NOT NULL DEFAULT 0,
    first_ts      TIMESTAMPTZ,
    last_ts       TIMESTAMPTZ,
    imported_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dataset_metadata (
    key        TEXT         PRIMARY KEY,
    value      TEXT         NOT NULL,
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
INSERT INTO dataset_metadata (key, value) VALUES
    ('bar_interval', '30 minutes'),
    ('source_timezone', 'America/New_York'),
    ('zero_volume_bars', 'omitted'),
    ('row_grain', 'one row per timestamp and instrument'),
    ('asset_types', 'stock, etf'),
    ('adjustment_layout', 'raw_* columns and adj_* columns'),
    ('price_storage', 'double precision'),
    ('volume_storage', 'bigint shares'),
    ('schema_version', '002_features')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

-- ── 1-minute bars (real-time accumulation: IBKR stream + Massive backfill) ────
-- Genuinely separate from the historical 30-min store; grows forward from today.
CREATE TABLE IF NOT EXISTS market_data_1min (
    time          TIMESTAMPTZ     NOT NULL,
    ticker        TEXT            NOT NULL,
    open          NUMERIC(14, 4)  NOT NULL,
    high          NUMERIC(14, 4)  NOT NULL,
    low           NUMERIC(14, 4)  NOT NULL,
    close         NUMERIC(14, 4)  NOT NULL,
    volume        BIGINT          NOT NULL,
    vwap          NUMERIC(14, 4),
    source        TEXT            NOT NULL DEFAULT 'ibkr'  -- 'ibkr' | 'massive' | 'polygon'
);
SELECT create_hypertable('market_data_1min', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_1min_ticker_time ON market_data_1min (ticker, time DESC);
-- Conflict target for the streams' idempotent upserts (ibkr_stream / massive_loader
-- re-emit the same minute as it fills / on re-run).
CREATE UNIQUE INDEX IF NOT EXISTS uq_1min_ticker_time ON market_data_1min (ticker, time);

-- ── Social media posts (Twitter / Reddit WSB) ────────────────────────────────
CREATE TABLE IF NOT EXISTS social_posts (
    id            UUID            NOT NULL DEFAULT uuid_generate_v4(),
    time          TIMESTAMPTZ     NOT NULL,
    ticker        TEXT,           -- NULL = macro/general sentiment
    platform      TEXT            NOT NULL,  -- 'twitter' | 'reddit'
    author        TEXT,
    content       TEXT            NOT NULL,
    url           TEXT,
    finbert_score NUMERIC(5, 4),  -- -1.0 to 1.0
    finbert_label TEXT,           -- 'positive' | 'negative' | 'neutral'
    embedding     VECTOR(384),    -- sentence-transformers MiniLM-L6
    is_vip        BOOLEAN         DEFAULT FALSE,  -- tracked influencer
    raw_metadata  JSONB,
    PRIMARY KEY (time, id)
);
SELECT create_hypertable('social_posts', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_posts_ticker_time ON social_posts (ticker, time DESC);
CREATE INDEX IF NOT EXISTS idx_posts_embedding ON social_posts USING ivfflat (embedding vector_cosine_ops);

-- ── News articles ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_articles (
    id            UUID            NOT NULL DEFAULT uuid_generate_v4(),
    time          TIMESTAMPTZ     NOT NULL,
    ticker        TEXT,
    headline      TEXT            NOT NULL,
    source        TEXT,
    -- No inline UNIQUE: a hypertable's unique indexes must include the
    -- partition column `time`. URL lookups/dedup go through idx_news_url below.
    url           TEXT,
    finbert_score NUMERIC(5, 4),
    finbert_label TEXT,
    embedding     VECTOR(384),
    raw_metadata  JSONB,
    PRIMARY KEY (time, id)
);
SELECT create_hypertable('news_articles', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_news_ticker_time ON news_articles (ticker, time DESC);
CREATE INDEX IF NOT EXISTS idx_news_url ON news_articles (url);
CREATE INDEX IF NOT EXISTS idx_news_url_ticker ON news_articles (url, ticker);
CREATE INDEX IF NOT EXISTS idx_news_finbert ON news_articles (ticker, finbert_label) WHERE finbert_label IS NOT NULL;

-- Auto-drop chunks older than 90 days (headlines stale, sentiment priced in)
SELECT add_retention_policy('news_articles', INTERVAL '90 days', if_not_exists => TRUE);

-- ── FOMC statements (global risk filter) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS fomc_statements (
    time           TIMESTAMPTZ     NOT NULL,
    document_url   TEXT,
    hawk_dove_score NUMERIC(5, 4), -- positive=hawkish, negative=dovish
    summary        TEXT,
    raw_text       TEXT
);
SELECT create_hypertable('fomc_statements', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fomc_time ON fomc_statements (time);
CREATE INDEX IF NOT EXISTS idx_fomc_document_url ON fomc_statements (document_url);
