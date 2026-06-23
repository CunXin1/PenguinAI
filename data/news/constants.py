"""Shared constants for the news module.

Two-axis schedule — WHICH tickers, and WHICH source:

  Tickers:
    TIER1 — MAG7 + top ETFs: every 5 min
    TIER2 — rest of hot tickers: every 20 min
    COLD  — everything else: on-demand only (no DB storage)

  Source (split-frequency, Google-primary):
    Google News RSS — free, near-real-time: runs EVERY cycle (the freshness baseline).
    Massive (paid)  — rich summary/image/ticker tags: only every MASSIVE_INTERVAL_MIN
                      (default 60 min), as a low-frequency enrichment layer.

Cadence was tightened (15/60 -> 5/20 min) once Google was merged in on every cycle:
re-polls are near-free because store_articles dedups by (url, ticker), so only
genuinely new rows are written. Override via the env vars below.
"""

HOT_ETFS = [
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO", "XLK", "XLF", "XLE", "XLV",
    "XLI", "SOXX", "SMH", "ARKK", "GLD", "SLV", "TLT", "HYG", "EEM", "VWO",
]

HOT_STOCKS = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "AVGO", "COST", "NFLX",
    "AMD", "ADBE", "CRM", "INTC", "QCOM", "TXN", "AMAT", "MU", "LRCX", "KLAC",
    "ORCL", "CSCO", "IBM", "NOW", "PANW", "CRWD", "SNOW", "PLTR", "COIN", "MSTR",
    "JPM", "V", "MA", "BAC", "GS", "MS", "BRK.B", "UNH", "JNJ", "PFE",
    "XOM", "CVX", "LLY", "ABBV", "MRK", "TMO", "WMT", "PG", "KO", "PEP",
    "TMUS", "CMCSA", "AMGN", "INTU", "HON", "ISRG", "BKNG", "SBUX", "VRTX",
    "ADP", "MDLZ", "GILD", "ADI", "REGN", "PYPL", "SNPS", "CDNS", "MRVL",
    "ARM", "SMCI", "RIVN", "MARA", "RIOT",
]

TIER1_TICKERS = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA",
    "SPY", "QQQ", "DIA", "IWM", "SOXX",
]

TIER2_TICKERS = sorted(set(HOT_STOCKS + HOT_ETFS) - set(TIER1_TICKERS))

HOT_TICKERS_LIST = sorted(set(HOT_STOCKS + HOT_ETFS))
HOT_TICKERS_SET = frozenset(HOT_TICKERS_LIST)

import os as _os

TIER1_INTERVAL_SEC = int(_os.getenv("NEWS_TIER1_INTERVAL_MIN", "5")) * 60
TIER2_INTERVAL_SEC = int(_os.getenv("NEWS_TIER2_INTERVAL_MIN", "20")) * 60
# Massive enrichment cadence — how often the paid source is layered on top of Google.
MASSIVE_INTERVAL_SEC = int(_os.getenv("NEWS_MASSIVE_INTERVAL_MIN", "60")) * 60

MAX_ARTICLES_PER_TICKER = int(_os.getenv("NEWS_MAX_PER_TICKER", "50"))
MAX_PER_TICKER_FEED = int(_os.getenv("NEWS_MAX_PER_TICKER_FEED", "3"))
