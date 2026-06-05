-- Recent wide rows for one symbol. One row = one timestamp + one instrument.
SELECT *
FROM v_bars_30m
WHERE symbol = 'AAPL'
  AND asset_type = 'stock'
ORDER BY ts DESC
LIMIT 50;

-- Adjusted AAPL bars over an Eastern-time date range.
SELECT
  et_time,
  symbol,
  adj_open AS open,
  adj_high AS high,
  adj_low AS low,
  adj_close AS close,
  adj_volume AS volume
FROM v_bars_30m
WHERE symbol = 'AAPL'
  AND asset_type = 'stock'
  AND et_time >= timestamp '2024-01-01 09:30:00'
  AND et_time < timestamp '2024-02-01 00:00:00'
ORDER BY ts;

-- Same table can query ETFs and stocks together.
SELECT
  et_time,
  symbol,
  asset_type,
  adj_close
FROM v_bars_30m
WHERE symbol IN ('AAPL', 'SPY')
  AND adj_close IS NOT NULL
ORDER BY ts, asset_type, symbol
LIMIT 100;

-- Long view if a library prefers one OHLCV set per row.
SELECT *
FROM v_bars_30m_long
WHERE symbol = 'SPY'
  AND asset_type = 'etf'
  AND adjustment = 'split_dividend_adjusted'
ORDER BY ts DESC
LIMIT 50;

-- Rebuild adjusted daily bars from 30-minute bars.
SELECT
  symbol,
  asset_type,
  time_bucket('1 day', ts, 'America/New_York') AS trading_day,
  first(adj_open, ts) AS open,
  max(adj_high) AS high,
  min(adj_low) AS low,
  last(adj_close, ts) AS close,
  sum(adj_volume) AS volume
FROM v_bars_30m
WHERE symbol = 'AAPL'
  AND asset_type = 'stock'
  AND adj_open IS NOT NULL
GROUP BY symbol, asset_type, trading_day
ORDER BY trading_day;

-- Import coverage summary.
SELECT
  i.symbol,
  i.asset_type,
  min(b.ts) AT TIME ZONE 'America/New_York' AS first_et,
  max(b.ts) AT TIME ZONE 'America/New_York' AS last_et,
  count(*) AS bars
FROM bars_30m b
JOIN instruments i ON i.instrument_id = b.instrument_id
GROUP BY i.symbol, i.asset_type
ORDER BY bars DESC
LIMIT 100;
