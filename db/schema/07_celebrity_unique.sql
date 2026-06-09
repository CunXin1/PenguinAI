-- Unique constraint for idempotent upserts into celebrity_holdings.
CREATE UNIQUE INDEX IF NOT EXISTS idx_celeb_unique_trade
    ON celebrity_holdings (celebrity, ticker, reported_at, action);

-- Fast celebrity-specific lookups (e.g. GET /api/celebrity-holdings/buffett).
CREATE INDEX IF NOT EXISTS idx_celeb_celebrity
    ON celebrity_holdings (celebrity, reported_at DESC);
