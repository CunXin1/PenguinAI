"""Real-time IBKR → ``market_data_1min`` ingestion service.

WHAT: a long-running process that subscribes to live 1-minute bars from
Interactive Brokers and upserts each bar into the ``market_data_1min``
hypertable. The FastAPI ``/api/market-data/{ticker}/candles?timeframe=1min``
endpoint reads from that table, so the frontend QQQ chart (polling) shows
near-real-time data once this service is running.

HOW IBKR works here (TWS API, via the ``ib_async`` maintained fork):
  * Requires TWS or IB Gateway running locally with the API enabled, plus a
    live/delayed market-data subscription for the tickers.
      TWS:  7496 live / 7497 paper.   Gateway: 4001 live / 4002 paper.
  * ``reqHistoricalData(barSizeSetting="1 min", keepUpToDate=True)`` returns a
    BarDataList that backfills recent bars and then keeps updating in place:
    each ``updateEvent`` carries the live-forming bar (and finalizes the prior
    one when ``hasNewBar`` is True). ``whatToShow="TRADES"``, ``useRTH=0`` keeps
    pre/post bars, ``formatDate=2`` returns UTC.
  * Each market-data line counts against IBKR's simultaneous-line limit
    (~100 by default), so keep the ticker list modest.

PIPELINE: IB updateEvent (sync callback) → asyncio.Queue → batched DB consumer
→ ``INSERT ... ON CONFLICT (ticker, time) DO UPDATE`` (idempotent: the same
minute is re-emitted every few seconds as it forms, then finalized).

RUN (from repo root, with .env present and TWS/Gateway + Postgres up):
    python -m data.ingestion.ibkr_stream
    python -m data.ingestion.ibkr_stream --symbols QQQ SPY --port 7497
    make ibkr-stream

This service CANNOT be exercised without a live Gateway/TWS + market-data
subscription + a reachable TimescaleDB.

VOLUME CAVEAT: IBKR stock volume has historically been reported in lots
(x100 shares). Charting ignores volume, but if you consume it elsewhere,
calibrate with --volume-scale.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("ibkr_stream")

# ── SQL ──────────────────────────────────────────────────────────────────────
# market_data_1min ships with only a (ticker, time) index, not a unique
# constraint — add one so upserts have a conflict target. Safe + idempotent.
_INDEX_SQL = text(
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_1min_ticker_time "
    "ON market_data_1min (ticker, time)"
)
_UPSERT_SQL = text(
    """
    INSERT INTO market_data_1min (time, ticker, open, high, low, close, volume, vwap, source)
    VALUES (:time, :ticker, :open, :high, :low, :close, :volume, :vwap, 'ibkr')
    ON CONFLICT (ticker, time) DO UPDATE SET
        open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
        close = EXCLUDED.close, volume = EXCLUDED.volume,
        vwap = EXCLUDED.vwap, source = 'ibkr'
    """
)


# ── Config ───────────────────────────────────────────────────────────────────
class StreamSettings(BaseSettings):
    """Env-backed defaults (reads the repo-root .env, like the rest of the app)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 7497
    # Distinct from ibkr_fetch.py (17) and the API default (1) so the stream can
    # run alongside other IB clients — each TWS connection needs a unique id.
    IBKR_CLIENT_ID: int = 2
    # Top-30 board (ETFs first), well within IBKR's default 100 market-data lines.
    IBKR_TICKERS: str = (
        "QQQ,SPY,IWM,DIA,NVDA,AAPL,MSFT,AMZN,GOOGL,META,TSLA,AVGO,AMD,NFLX,PLTR,"
        "COIN,MU,QCOM,JPM,V,GS,LLY,UNH,XOM,CVX,COST,WMT,BAC,ORCL,CRM"
    )


@dataclass(slots=True)
class StreamConfig:
    host: str
    port: int
    client_id: int
    tickers: list[str]
    database_url: str
    connect_timeout: float
    reconnect_delay: float
    backfill: str
    volume_scale: float


# ── Bar → row helpers ────────────────────────────────────────────────────────
def _to_utc(bar_date: object) -> datetime | None:
    """Normalize an ``ib_async`` BarData.date (UTC datetime / epoch / date) to UTC."""
    if isinstance(bar_date, bool):
        return None
    if isinstance(bar_date, (int, float)):
        return datetime.fromtimestamp(bar_date, tz=UTC)
    if isinstance(bar_date, datetime):
        return bar_date.astimezone(UTC) if bar_date.tzinfo else bar_date.replace(tzinfo=UTC)
    if isinstance(bar_date, date):
        return datetime(bar_date.year, bar_date.month, bar_date.day, tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(bar_date)).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _bar_to_row(ticker: str, bar: object, volume_scale: float) -> dict | None:
    """Convert one BarData to an upsert param dict, or None if it's empty/invalid."""
    t = _to_utc(getattr(bar, "date", None))
    o = getattr(bar, "open", None)
    h = getattr(bar, "high", None)
    low = getattr(bar, "low", None)
    c = getattr(bar, "close", None)
    # IB sends -1 for OHLC on bars with no trades (TRADES whatToShow) — skip those.
    if t is None or None in (o, h, low, c) or o <= 0 or h <= 0:
        return None
    raw_vol = getattr(bar, "volume", 0) or 0
    volume = int(round(raw_vol * volume_scale)) if raw_vol > 0 else 0
    avg = getattr(bar, "average", None)
    vwap = float(avg) if avg not in (None, -1, -1.0) else None
    return {
        "time": t,
        "ticker": ticker,
        "open": float(o),
        "high": float(h),
        "low": float(low),
        "close": float(c),
        "volume": volume,
        "vwap": vwap,
    }


def _make_handler(ticker: str, queue: asyncio.Queue, volume_scale: float):
    """Build the ib_async ``updateEvent`` callback for one ticker (sync → enqueue)."""

    def _on_update(bars, has_new_bar: bool) -> None:  # noqa: FBT001 (ib_async signature)
        if not bars:
            return
        # On a new bar, also finalize the now-closed previous bar.
        recent = bars[-2:] if (has_new_bar and len(bars) >= 2) else bars[-1:]
        for b in recent:
            row = _bar_to_row(ticker, b, volume_scale)
            if row is None:
                continue
            try:
                queue.put_nowait(row)
            except asyncio.QueueFull:
                logger.warning("queue full — dropping %s bar @ %s", ticker, row["time"])

    return _on_update


# ── DB consumer ──────────────────────────────────────────────────────────────
async def _ensure_index(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(_INDEX_SQL)
    logger.info("ensured unique index uq_1min_ticker_time on market_data_1min")


async def _upsert(engine, rows: list[dict]) -> None:
    async with engine.begin() as conn:
        await conn.execute(_UPSERT_SQL, rows)


async def _db_consumer(engine, queue: asyncio.Queue) -> None:
    """Drain the queue and upsert bars in batches until cancelled."""
    written = 0
    try:
        while True:
            first = await queue.get()
            batch = [first]
            while len(batch) < 500:
                try:
                    batch.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                await _upsert(engine, batch)
                written += len(batch)
                if written % 200 < len(batch):
                    logger.info("upserted ~%d bars total", written)
            except Exception as exc:  # noqa: BLE001 — keep the consumer alive on DB hiccups
                logger.error("db upsert failed (%d rows): %r", len(batch), exc)
    except asyncio.CancelledError:
        logger.info("db consumer stopped (%d bars written)", written)
        raise


# ── IB subscription + run loop ───────────────────────────────────────────────
async def _subscribe(ib, cfg: StreamConfig, queue: asyncio.Queue) -> None:
    from ib_async import Stock  # lazy: keeps import/py_compile working without TWS deps

    for tk in cfg.tickers:
        contract = Stock(tk, "SMART", "USD")
        if not await ib.qualifyContractsAsync(contract):
            logger.warning("could not qualify %s — skipping", tk)
            continue
        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=cfg.backfill,
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=2,
            keepUpToDate=True,
        )
        backfilled = 0
        for b in bars:
            row = _bar_to_row(tk, b, cfg.volume_scale)
            if row is None:
                continue
            try:
                queue.put_nowait(row)
                backfilled += 1
            except asyncio.QueueFull:
                break
        bars.updateEvent += _make_handler(tk, queue, cfg.volume_scale)
        logger.info("subscribed %s (%d backfill bars)", tk, backfilled)


async def run_stream(cfg: StreamConfig) -> None:
    from ib_async import IB  # lazy import

    engine = create_async_engine(cfg.database_url)
    await _ensure_index(engine)
    queue: asyncio.Queue = asyncio.Queue(maxsize=20_000)
    consumer = asyncio.create_task(_db_consumer(engine, queue))
    ib = IB()
    stop = asyncio.Event()

    try:
        while not stop.is_set():
            try:
                logger.info(
                    "connecting %s:%s clientId=%s ...", cfg.host, cfg.port, cfg.client_id
                )
                await ib.connectAsync(
                    cfg.host,
                    cfg.port,
                    clientId=cfg.client_id,
                    timeout=cfg.connect_timeout,
                    readonly=True,
                )
                logger.info("connected — subscribing %d ticker(s)", len(cfg.tickers))
                await _subscribe(ib, cfg, queue)
                logger.info("streaming live 1-min bars (Ctrl-C to stop)")
                while ib.isConnected() and not stop.is_set():
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                stop.set()
                raise
            except Exception as exc:  # noqa: BLE001 — reconnect on any IB/socket error
                logger.error("stream error: %r", exc)
            finally:
                if ib.isConnected():
                    ib.disconnect()
            if not stop.is_set():
                logger.info("reconnecting in %.0fs ...", cfg.reconnect_delay)
                await asyncio.sleep(cfg.reconnect_delay)
    finally:
        consumer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer
        await engine.dispose()


# ── CLI ──────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stream live IBKR 1-min bars into market_data_1min.")
    p.add_argument("--host", default=None, help="TWS/Gateway host (default: env IBKR_HOST).")
    p.add_argument("--port", type=int, default=None, help="7496/7497 TWS, 4001/4002 Gateway.")
    p.add_argument("--client-id", type=int, default=None, help="Unique IB client id (env default 2).")
    p.add_argument("--symbols", nargs="*", default=None, help="Tickers (default: env IBKR_TICKERS).")
    p.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    p.add_argument("--connect-timeout", type=float, default=20.0)
    p.add_argument("--reconnect-delay", type=float, default=10.0)
    p.add_argument("--backfill", default="3600 S", help="Initial history duration (IB durationStr).")
    p.add_argument(
        "--volume-scale",
        type=float,
        default=1.0,
        help="Multiply IBKR volume (historically lots x100 for stocks).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    s = StreamSettings()
    raw_tickers = args.symbols if args.symbols else s.IBKR_TICKERS.split(",")
    tickers = [t.strip().upper() for t in raw_tickers if t.strip()]
    cfg = StreamConfig(
        host=args.host or s.IBKR_HOST,
        port=args.port or s.IBKR_PORT,
        client_id=args.client_id if args.client_id is not None else s.IBKR_CLIENT_ID,
        tickers=tickers,
        database_url=args.database_url or s.DATABASE_URL,
        connect_timeout=args.connect_timeout,
        reconnect_delay=args.reconnect_delay,
        backfill=args.backfill,
        volume_scale=args.volume_scale,
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not cfg.tickers:
        logger.error("no tickers configured (set IBKR_TICKERS or pass --symbols)")
        return
    logger.info("IBKR stream → market_data_1min | tickers=%s", ",".join(cfg.tickers))
    try:
        asyncio.run(run_stream(cfg))
    except KeyboardInterrupt:
        logger.info("interrupted — shutting down")


if __name__ == "__main__":
    main()
