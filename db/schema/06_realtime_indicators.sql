-- ─────────────────────────────────────────────────────────────────────────────
-- REAL-TIME 1-MIN INDICATORS  (extends market_data_1min in place)
-- ─────────────────────────────────────────────────────────────────────────────
--
-- market_data_1min is the forward-accumulating 1-minute table (fed by the IBKR
-- stream + Massive poller). The realtime ingestion supervisor computes the SAME
-- indicator family as bars_30m on a recent 1-min window and upserts the values
-- back here — so the live 1-min series carries indicators without a separate
-- table, and the ticker-keyed live model stays intact.
--
-- Idempotent ADD COLUMN IF NOT EXISTS — safe to re-run. Existing OHLCV rows keep
-- NULL indicators until the supervisor (re)computes them. `vwap_day` is the
-- session-cumulative VWAP (distinct from the per-bar `vwap` already on the table).

ALTER TABLE market_data_1min
    ADD COLUMN IF NOT EXISTS rth         BOOLEAN,
    ADD COLUMN IF NOT EXISTS sma_20      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS sma_50      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS sma_200     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema_12      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema_26      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ema_50      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS macd        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS macd_signal DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS macd_hist   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS rsi_14      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bb_mid      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bb_upper    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bb_lower    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bb_pctb     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bb_bw       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS atr_14      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS obv         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS vwap_day    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ret_1bar    DOUBLE PRECISION;
