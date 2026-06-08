-- ─────────────────────────────────────────────────────────────────────────────
-- RELATIONAL TABLES  (standard PostgreSQL)
-- ─────────────────────────────────────────────────────────────────────────────

-- Users
CREATE TABLE IF NOT EXISTS users (
    id             UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    email          TEXT        UNIQUE NOT NULL,
    password_hash  TEXT,
    display_name   TEXT,
    oauth_provider TEXT,       -- 'google' | 'apple' | NULL (email/password)
    oauth_sub      TEXT,
    tier           TEXT        NOT NULL DEFAULT 'FREE',  -- FREE | PRO | PREMIUM | ADMIN
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    email_verified BOOLEAN     NOT NULL DEFAULT FALSE,
    token_version  INTEGER     NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_oauth ON users (oauth_provider, oauth_sub);

-- Stock universe (2000 tickers)
CREATE TABLE IF NOT EXISTS tickers (
    ticker        TEXT        PRIMARY KEY,
    name          TEXT        NOT NULL,
    exchange      TEXT,       -- 'NASDAQ' | 'NYSE' | 'CRYPTO'
    sector        TEXT,
    industry      TEXT,
    market_cap    BIGINT,
    tags          TEXT[]      DEFAULT '{}',  -- ['tech', 'etf', 'crypto', 'ipo', 'sp500']
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
    data_start    DATE,       -- earliest available bar date
    added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tickers_tags ON tickers USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_tickers_active ON tickers (is_active);

-- User watchlists
CREATE TABLE IF NOT EXISTS watchlists (
    user_id       UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker        TEXT        NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, ticker)
);

-- Signal cache (pre-computed top-100 + on-demand cold stocks)
CREATE TABLE IF NOT EXISTS signal_cache (
    ticker         TEXT        PRIMARY KEY,
    direction      TEXT        NOT NULL,  -- 'LONG' | 'SHORT' | 'NEUTRAL'
    confidence     NUMERIC(5, 4) NOT NULL,
    holding_period TEXT        NOT NULL,  -- 'INTRADAY' | 'SHORT_TERM' | 'SWING' | 'POSITION'
    -- ML scores
    xgb_prob_up   NUMERIC(5, 4),
    rf_prob_up    NUMERIC(5, 4),
    ensemble_prob NUMERIC(5, 4),
    -- Sentiment
    finbert_score  NUMERIC(5, 4),
    post_count     INT,
    hawk_dove_ref  NUMERIC(5, 4),
    -- AI output
    ai_attribution TEXT,
    ai_analysis    TEXT,
    -- Meta
    tier_required  TEXT        NOT NULL DEFAULT 'FREE',
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signal_expires ON signal_cache (expires_at);

-- Celebrity / insider holdings (13F + daily disclosures)
CREATE TABLE IF NOT EXISTS celebrity_holdings (
    id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    reported_at   TIMESTAMPTZ NOT NULL,
    celebrity     TEXT        NOT NULL,  -- 'buffett' | 'cathie_wood' | 'pelosi'
    ticker        TEXT        REFERENCES tickers(ticker),
    action        TEXT        NOT NULL,  -- 'BUY' | 'SELL' | 'HOLD'
    shares        BIGINT,
    value_usd     BIGINT,
    source_type   TEXT        NOT NULL,  -- '13F' | 'daily_disclosure'
    filing_url    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_celeb_ticker ON celebrity_holdings (ticker, reported_at DESC);

-- Earnings data
CREATE TABLE IF NOT EXISTS earnings (
    ticker            TEXT        NOT NULL REFERENCES tickers(ticker),
    report_date       DATE        NOT NULL,
    eps_actual        NUMERIC(10, 4),
    eps_estimate      NUMERIC(10, 4),
    eps_surprise_pct  NUMERIC(8, 4),
    revenue_actual    BIGINT,
    revenue_estimate  BIGINT,
    guidance_text     TEXT,
    report_hour       TEXT,       -- 'bmo' | 'amc' | 'dmh' (Finnhub hour) → UI session badge
    PRIMARY KEY (ticker, report_date)
);

-- Fundamentals snapshot (daily)
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker          TEXT        NOT NULL REFERENCES tickers(ticker),
    date            DATE        NOT NULL,
    pe_ratio        NUMERIC(10, 4),
    pb_ratio        NUMERIC(10, 4),
    ps_ratio        NUMERIC(10, 4),
    market_cap      BIGINT,
    shares_out      BIGINT,
    PRIMARY KEY (ticker, date)
);

-- ML model registry
CREATE TABLE IF NOT EXISTS ml_models (
    id             UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_type     TEXT        NOT NULL,  -- 'xgboost' | 'random_forest'
    version        TEXT        NOT NULL,
    artifact_path  TEXT        NOT NULL,
    metrics        JSONB,
    is_production  BOOLEAN     NOT NULL DEFAULT FALSE,
    trained_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ml_models_prod ON ml_models (model_type, is_production);

-- User-requested symbols not in our universe (data-demand queue).
-- A search for a symbol we don't cover lands here; a background job validates
-- it against Massive (Polygon-compatible reference API) and classifies it.
CREATE TABLE IF NOT EXISTS symbol_requests (
    symbol             TEXT        PRIMARY KEY,
    request_count      INT         NOT NULL DEFAULT 1,
    status             TEXT        NOT NULL DEFAULT 'pending',
        -- pending            : awaiting validation
        -- real_pending_ingest: Massive confirms a live ticker we simply lack data for
        -- delisted           : Massive knows it but it is inactive/delisted
        -- rejected_junk      : Massive has no record → typo / non-existent
        -- ingested           : data backfilled + promoted into `tickers`
    resolved_name      TEXT,       -- company/ETF name from Massive (if real)
    resolved_exchange  TEXT,       -- primary exchange from Massive (if real)
    note               TEXT,       -- classifier detail (e.g. Massive `type`)
    first_requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_requested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    validated_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_symbol_requests_status ON symbol_requests (status);
CREATE INDEX IF NOT EXISTS idx_symbol_requests_demand ON symbol_requests (request_count DESC);
