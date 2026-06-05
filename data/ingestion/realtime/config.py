"""Realtime ingestion config — env settings + the streamed/polled symbol universe."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class RealtimeSettings(BaseSettings):
    """Env-backed (reads the repo-root .env, like the rest of the app)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    MASSIVE_API_KEY: str = ""
    MASSIVE_BASE_URL: str = "https://api.massive.com"

    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 7497  # 7496/7497 TWS live/paper · 4001/4002 Gateway
    IBKR_CLIENT_ID: int = 3  # distinct from ibkr_stream.py (2) and the API (1)

    # Master switch the FastAPI lifespan checks before spawning the supervisor.
    REALTIME_ENABLED: bool = True
    # Poll cadences (seconds)
    MASSIVE_POLL_INTERVAL: int = 60
    IBKR_ENABLED: bool = True  # set false to run Massive-only (no TWS)


# ── IBKR-streamed set: 10 ETFs + 40 stocks, by 60-day ADDV (dollar volume) ────
# Data-driven pick (2026-06-05, from bars_30m). Edit freely; the Massive poller
# automatically covers whatever 1-min symbols are NOT in this list.
IBKR_ETFS = ["SPY", "QQQ", "SOXL", "IWM", "TQQQ", "SMH", "VOO", "SOXX", "HYG", "LQD"]
IBKR_STOCKS = [
    "MU", "NVDA", "TSLA", "SNDK", "INTC", "AMD", "MSFT", "AAPL", "AMZN", "META",
    "GOOGL", "AVGO", "PLTR", "MRVL", "GOOG", "TSM", "ORCL", "LITE", "QCOM", "CRWV",
    "NFLX", "NOW", "NBIS", "CBRS", "WDC", "ARM", "RKLB", "MSTR", "IREN", "STX",
    "DELL", "HOOD", "BE", "LLY", "ASML", "UNH", "GEV", "IBM", "APP", "CRM",
]
IBKR_SYMBOLS: list[str] = IBKR_ETFS + IBKR_STOCKS
