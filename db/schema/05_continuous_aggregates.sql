-- ─────────────────────────────────────────────────────────────────────────────
-- CONTINUOUS AGGREGATES  (TimescaleDB, pre-materialized rollups)
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Daily OHLCV rolled up from market_data_1min. The /market-data/{ticker}/series
-- endpoint reads this for the 3M/1Y chart ranges so a year of minute bars
-- (~350k rows/ticker) doesn't get rescanned on every request (3s → ~10ms).

CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_1d_cagg
WITH (timescaledb.continuous) AS
SELECT ticker,
       time_bucket('1 day', time) AS day,
       first(open, time) AS open,
       max(high)         AS high,
       min(low)          AS low,
       last(close, time) AS close,
       sum(volume)       AS volume
FROM market_data_1min
GROUP BY ticker, time_bucket('1 day', time)
WITH NO DATA;

-- Keep it current as new minute bars stream in (IBKR / Massive).
SELECT add_continuous_aggregate_policy('market_data_1d_cagg',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);

-- Initial materialization (no-op on a fresh/empty DB; after a bulk minute load
-- run this once to populate immediately rather than waiting for the policy):
--   CALL refresh_continuous_aggregate('market_data_1d_cagg', NULL, NULL);
