from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    import psycopg
except ModuleNotFoundError:
    psycopg = None


RAW = "raw"
ADJUSTED = "split_dividend_adjusted"
EASTERN_SUFFIX = " America/New_York"

PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
WIDE_COLUMNS = (
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "adj_volume",
)

COPY_SQL = """
COPY stage_bars_30m (
  ts,
  instrument_id,
  raw_open,
  raw_high,
  raw_low,
  raw_close,
  raw_volume,
  adj_open,
  adj_high,
  adj_low,
  adj_close,
  adj_volume
) FROM STDIN
"""


@dataclass
class FileStat:
    source_file: str
    symbol: str | None
    asset_type: str
    rows_seen: int = 0
    rows_valid: int = 0
    rows_invalid: int = 0
    first_ts: str | datetime | None = None
    last_ts: str | datetime | None = None

    def mark_et_time(self, dt: str) -> None:
        if self.first_ts is None or str(dt) < str(self.first_ts):
            self.first_ts = dt
        if self.last_ts is None or str(dt) > str(self.last_ts):
            self.last_ts = dt

    def mark_ts(self, ts: datetime) -> None:
        if self.first_ts is None or ts < self.first_ts:
            self.first_ts = ts
        if self.last_ts is None or ts > self.last_ts:
            self.last_ts = ts


class StageWriter:
    def __init__(self, conn: psycopg.Connection, batch_rows: int) -> None:
        self.conn = conn
        self.batch_rows = batch_rows
        self.pending_rows = 0
        self.total_upserted = 0
        self._copy = None
        self._copy_cm = None
        self._cursor = None

    def write_adjusted_side(
        self,
        ts: str | datetime,
        instrument_id: int,
        adjustment: str,
        values: tuple[float, float, float, float, int],
    ) -> None:
        empty = (None, None, None, None, None)
        if adjustment == RAW:
            self.write_wide(ts, instrument_id, values, empty)
        elif adjustment == ADJUSTED:
            self.write_wide(ts, instrument_id, empty, values)
        else:
            raise ValueError(f"unknown adjustment: {adjustment}")

    def write_wide(
        self,
        ts: str | datetime,
        instrument_id: int,
        raw_values: tuple[float, float, float, float, int] | tuple[None, None, None, None, None],
        adj_values: tuple[float, float, float, float, int] | tuple[None, None, None, None, None],
    ) -> None:
        if self._copy is None:
            self._cursor = self.conn.cursor()
            self._copy_cm = self._cursor.copy(COPY_SQL)
            self._copy = self._copy_cm.__enter__()

        self._copy.write_row((ts, instrument_id, *raw_values, *adj_values))
        self.pending_rows += 1

        if self.pending_rows >= self.batch_rows:
            self.flush()

    def flush(self) -> int:
        if self._copy is not None:
            self._copy_cm.__exit__(None, None, None)
            self._copy = None
            self._copy_cm = None
            self._cursor.close()
            self._cursor = None

        if self.pending_rows == 0:
            return 0

        affected = self.conn.execute(
            """
            WITH collapsed AS (
              SELECT
                ts,
                instrument_id,
                max(raw_open) FILTER (WHERE raw_open IS NOT NULL) AS raw_open,
                max(raw_high) FILTER (WHERE raw_high IS NOT NULL) AS raw_high,
                max(raw_low) FILTER (WHERE raw_low IS NOT NULL) AS raw_low,
                max(raw_close) FILTER (WHERE raw_close IS NOT NULL) AS raw_close,
                max(raw_volume) FILTER (WHERE raw_volume IS NOT NULL) AS raw_volume,
                max(adj_open) FILTER (WHERE adj_open IS NOT NULL) AS adj_open,
                max(adj_high) FILTER (WHERE adj_high IS NOT NULL) AS adj_high,
                max(adj_low) FILTER (WHERE adj_low IS NOT NULL) AS adj_low,
                max(adj_close) FILTER (WHERE adj_close IS NOT NULL) AS adj_close,
                max(adj_volume) FILTER (WHERE adj_volume IS NOT NULL) AS adj_volume
              FROM stage_bars_30m
              GROUP BY ts, instrument_id
            ),
            upserted AS (
              INSERT INTO bars_30m (
                ts,
                instrument_id,
                raw_open,
                raw_high,
                raw_low,
                raw_close,
                raw_volume,
                adj_open,
                adj_high,
                adj_low,
                adj_close,
                adj_volume
              )
              SELECT
                ts,
                instrument_id,
                raw_open,
                raw_high,
                raw_low,
                raw_close,
                raw_volume,
                adj_open,
                adj_high,
                adj_low,
                adj_close,
                adj_volume
              FROM collapsed
              ON CONFLICT (ts, instrument_id) DO UPDATE
              SET raw_open = COALESCE(EXCLUDED.raw_open, bars_30m.raw_open),
                  raw_high = COALESCE(EXCLUDED.raw_high, bars_30m.raw_high),
                  raw_low = COALESCE(EXCLUDED.raw_low, bars_30m.raw_low),
                  raw_close = COALESCE(EXCLUDED.raw_close, bars_30m.raw_close),
                  raw_volume = COALESCE(EXCLUDED.raw_volume, bars_30m.raw_volume),
                  adj_open = COALESCE(EXCLUDED.adj_open, bars_30m.adj_open),
                  adj_high = COALESCE(EXCLUDED.adj_high, bars_30m.adj_high),
                  adj_low = COALESCE(EXCLUDED.adj_low, bars_30m.adj_low),
                  adj_close = COALESCE(EXCLUDED.adj_close, bars_30m.adj_close),
                  adj_volume = COALESCE(EXCLUDED.adj_volume, bars_30m.adj_volume),
                  updated_at = now()
              RETURNING 1
            )
            SELECT count(*) FROM upserted
            """
        ).fetchone()[0]

        self.conn.execute(
            """
            UPDATE instruments i
            SET first_ts = CASE
                    WHEN i.first_ts IS NULL THEN s.first_ts
                    ELSE LEAST(i.first_ts, s.first_ts)
                  END,
                last_ts = CASE
                    WHEN i.last_ts IS NULL THEN s.last_ts
                    ELSE GREATEST(i.last_ts, s.last_ts)
                  END,
                updated_at = now()
            FROM (
              SELECT instrument_id, min(ts) AS first_ts, max(ts) AS last_ts
              FROM stage_bars_30m
              GROUP BY instrument_id
            ) s
            WHERE i.instrument_id = s.instrument_id
            """
        )
        self.conn.execute("TRUNCATE stage_bars_30m")
        self.conn.commit()

        self.total_upserted += affected
        flushed = self.pending_rows
        self.pending_rows = 0
        return flushed


def parse_years(spec: str | None) -> set[int] | None:
    if not spec:
        return None
    years: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            years.update(range(int(start), int(end) + 1))
        else:
            years.add(int(part))
    return years


def parse_symbols(spec: str | None) -> set[str] | None:
    if not spec:
        return None
    return {item.strip().upper() for item in spec.split(",") if item.strip()}


def connect() -> psycopg.Connection:
    if psycopg is None:
        raise RuntimeError("psycopg is required for database import. Run this script with the loader container.")
    # Defaults target the app DB (penguinai docker container). Override via PG* env.
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "penguinai"),
        user=os.getenv("PGUSER", "penguinai"),
        password=os.getenv("PGPASSWORD", "penguinai_dev"),
    )


def split_sql(sql_text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).rstrip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
    if current:
        statements.append("\n".join(current).strip())
    return statements


def init_schema(conn: psycopg.Connection, schema_file: str) -> None:
    sql_text = Path(schema_file).read_text(encoding="utf-8")
    for statement in split_sql(sql_text):
        conn.execute(statement)
    conn.commit()


def ensure_stage(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS stage_bars_30m (
          ts TIMESTAMPTZ NOT NULL,
          instrument_id BIGINT NOT NULL,
          raw_open DOUBLE PRECISION,
          raw_high DOUBLE PRECISION,
          raw_low DOUBLE PRECISION,
          raw_close DOUBLE PRECISION,
          raw_volume BIGINT,
          adj_open DOUBLE PRECISION,
          adj_high DOUBLE PRECISION,
          adj_low DOUBLE PRECISION,
          adj_close DOUBLE PRECISION,
          adj_volume BIGINT
        ) ON COMMIT PRESERVE ROWS
        """
    )
    conn.execute("TRUNCATE stage_bars_30m")
    conn.commit()


def preload_instruments(conn: psycopg.Connection, instruments: Iterable[tuple[str, str]]) -> dict[tuple[str, str], int]:
    instrument_rows = sorted(set(instruments))
    if instrument_rows:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO instruments (symbol, asset_type)
                VALUES (%s, %s)
                ON CONFLICT (symbol, asset_type) DO NOTHING
                """,
                instrument_rows,
            )
        conn.commit()

    rows = conn.execute("SELECT instrument_id, symbol, asset_type FROM instruments").fetchall()
    return {(row[1], row[2]): row[0] for row in rows}


def start_run(
    conn: psycopg.Connection,
    input_format: str,
    scope: str,
    years: str | None,
    symbols: str | None,
    files_planned: int,
) -> int:
    return conn.execute(
        """
        INSERT INTO import_runs (
          input_format,
          scope,
          years_filter,
          symbols_filter,
          files_planned
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING import_run_id
        """,
        (input_format, scope, years, symbols, files_planned),
    ).fetchone()[0]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    files_seen: int,
    rows_seen: int,
    rows_loaded: int,
    rows_invalid: int,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE import_runs
        SET finished_at = now(),
            status = %s,
            files_seen = %s,
            rows_seen = %s,
            rows_loaded = %s,
            rows_invalid = %s,
            notes = %s
        WHERE import_run_id = %s
        """,
        (status, files_seen, rows_seen, rows_loaded, rows_invalid, notes, run_id),
    )
    conn.commit()


def normalize_timestamp(value: str | datetime | None) -> str | datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if "+" in value or value.endswith("Z"):
        return value
    return value + EASTERN_SUFFIX


def upsert_file_stats(conn: psycopg.Connection, run_id: int, file_stats: list[FileStat]) -> None:
    if not file_stats:
        return

    records = [
        (
            stat.source_file,
            stat.symbol,
            stat.asset_type,
            run_id,
            stat.rows_seen,
            stat.rows_valid,
            stat.rows_invalid,
            normalize_timestamp(stat.first_ts),
            normalize_timestamp(stat.last_ts),
        )
        for stat in file_stats
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO import_files (
              source_file,
              symbol,
              asset_type,
              import_run_id,
              rows_seen,
              rows_valid,
              rows_invalid,
              first_ts,
              last_ts
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_file) DO UPDATE
            SET symbol = EXCLUDED.symbol,
                asset_type = EXCLUDED.asset_type,
                import_run_id = EXCLUDED.import_run_id,
                rows_seen = EXCLUDED.rows_seen,
                rows_valid = EXCLUDED.rows_valid,
                rows_invalid = EXCLUDED.rows_invalid,
                first_ts = EXCLUDED.first_ts,
                last_ts = EXCLUDED.last_ts,
                imported_at = now()
            """,
            records,
        )
    conn.commit()
