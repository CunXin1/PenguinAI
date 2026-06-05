-- ─────────────────────────────────────────────────────────────────────────────
-- TIME-SERIES TABLES  (TimescaleDB Hypertables)
-- ─────────────────────────────────────────────────────────────────────────────

-- 30-minute bars (primary historical dataset, 2000–present)
CREATE TABLE IF NOT EXISTS market_data_30min (
    time          TIMESTAMPTZ     NOT NULL,
    ticker        TEXT            NOT NULL,
    open          NUMERIC(14, 4)  NOT NULL,
    high          NUMERIC(14, 4)  NOT NULL,
    low           NUMERIC(14, 4)  NOT NULL,
    close         NUMERIC(14, 4)  NOT NULL,
    volume        BIGINT          NOT NULL,
    vwap          NUMERIC(14, 4),
    adjusted      BOOLEAN         NOT NULL DEFAULT TRUE,
    source        TEXT            NOT NULL DEFAULT 'import'  -- 'import' | 'ibkr' | 'polygon'
);
SELECT create_hypertable('market_data_30min', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_30min_ticker_time ON market_data_30min (ticker, time DESC);

-- 1-minute bars (real-time accumulation from IBKR, grows daily)
CREATE TABLE IF NOT EXISTS market_data_1min (
    time          TIMESTAMPTZ     NOT NULL,
    ticker        TEXT            NOT NULL,
    open          NUMERIC(14, 4)  NOT NULL,
    high          NUMERIC(14, 4)  NOT NULL,
    low           NUMERIC(14, 4)  NOT NULL,
    close         NUMERIC(14, 4)  NOT NULL,
    volume        BIGINT          NOT NULL,
    vwap          NUMERIC(14, 4),
    source        TEXT            NOT NULL DEFAULT 'ibkr'
);
SELECT create_hypertable('market_data_1min', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_1min_ticker_time ON market_data_1min (ticker, time DESC);
-- Conflict target for the real-time IBKR stream's idempotent upserts
-- (data/ingestion/ibkr_stream.py re-emits the forming minute as it fills).
CREATE UNIQUE INDEX IF NOT EXISTS uq_1min_ticker_time ON market_data_1min (ticker, time);

-- Daily bars (lightweight, for macro context)
CREATE TABLE IF NOT EXISTS market_data_daily (
    time          TIMESTAMPTZ     NOT NULL,
    ticker        TEXT            NOT NULL,
    open          NUMERIC(14, 4)  NOT NULL,
    high          NUMERIC(14, 4)  NOT NULL,
    low           NUMERIC(14, 4)  NOT NULL,
    close         NUMERIC(14, 4)  NOT NULL,
    volume        BIGINT          NOT NULL,
    adjusted_close NUMERIC(14, 4),
    source        TEXT            NOT NULL DEFAULT 'polygon'
);
SELECT create_hypertable('market_data_daily', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_daily_ticker_time ON market_data_daily (ticker, time DESC);

-- Technical indicators aligned to 30-min bars
CREATE TABLE IF NOT EXISTS indicators_30min (
    time          TIMESTAMPTZ     NOT NULL,
    ticker        TEXT            NOT NULL,
    -- Momentum
    rsi_14        NUMERIC(7, 4),
    macd          NUMERIC(12, 6),
    macd_signal   NUMERIC(12, 6),
    macd_hist     NUMERIC(12, 6),
    -- Volatility
    bb_upper      NUMERIC(14, 4),
    bb_middle     NUMERIC(14, 4),
    bb_lower      NUMERIC(14, 4),
    atr_14        NUMERIC(12, 6),
    -- Volume
    volume_sma20  BIGINT,
    obv           BIGINT,
    -- Trend
    ema_20        NUMERIC(14, 4),
    ema_50        NUMERIC(14, 4),
    sma_200       NUMERIC(14, 4),
    -- Intraday
    vwap_session  NUMERIC(14, 4)
);
SELECT create_hypertable('indicators_30min', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ind30_ticker_time ON indicators_30min (ticker, time DESC);

-- Social media posts (Twitter / Reddit WSB)
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

-- News articles
CREATE TABLE IF NOT EXISTS news_articles (
    id            UUID            NOT NULL DEFAULT uuid_generate_v4(),
    time          TIMESTAMPTZ     NOT NULL,
    ticker        TEXT,
    headline      TEXT            NOT NULL,
    source        TEXT,
    url           TEXT            UNIQUE,
    finbert_score NUMERIC(5, 4),
    finbert_label TEXT,
    embedding     VECTOR(384),
    raw_metadata  JSONB,
    PRIMARY KEY (time, id)
);
SELECT create_hypertable('news_articles', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_news_ticker_time ON news_articles (ticker, time DESC);
CREATE INDEX IF NOT EXISTS idx_news_url ON news_articles (url);

-- FOMC statements (global risk filter)
CREATE TABLE IF NOT EXISTS fomc_statements (
    time           TIMESTAMPTZ     NOT NULL,
    document_url   TEXT,
    hawk_dove_score NUMERIC(5, 4), -- positive=hawkish, negative=dovish
    summary        TEXT,
    raw_text       TEXT
);
SELECT create_hypertable('fomc_statements', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_fomc_document_url ON fomc_statements (document_url);
