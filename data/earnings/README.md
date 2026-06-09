# data/earnings/

Finnhub earnings calendar ingestion + scheduler for the `earnings` table.

## Files

| File | Purpose |
|------|---------|
| `finnhub.py` | Loads Finnhub free-tier earnings calendar → `earnings` table (idempotent upserts) |
| `scheduler.py` | Background scheduler: startup fetch + 2×/day (08:00 + 18:00 ET weekdays) |

## Quick Start

```bash
# One-shot fetch (requires FINNHUB_API_KEY in .env)
make fetch-earnings

# Backfill 1 year
python -m data.earnings.finnhub --days-back 365

# Specific range
python -m data.earnings.finnhub --from 2025-01-01 --to 2025-12-31
```

## Auto-Schedule

The backend lifespan starts `scheduler.run_scheduler()` in a daemon thread:
- **Startup**: immediate fetch (ensures core tickers exist + pulls calendar)
- **08:00 ET**: pre-market (BMO actuals + refreshed calendar)
- **18:00 ET**: post-market (AMC actuals)
- Weekends skipped

## Core Tickers

`scheduler._CORE_STOCKS` (50 symbols) are auto-inserted into `tickers` before each fetch,
guaranteeing FK coverage for all IBKR-streamed stocks without depending on `make bootstrap`.

## See Also

- `docs/earnings.md` — full module documentation
- `backend/app/api/routes/earnings.py` — API endpoints
- `frontend/src/app/earnings/page.tsx` — UI
