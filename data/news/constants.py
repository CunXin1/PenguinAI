"""Shared constants for the news module.

Three fetch tiers:
  TIER1 — MAG7 + top ETFs: every 15 min during market hours
  TIER2 — rest of hot tickers: every 60 min
  COLD  — everything else: on-demand only (no DB storage)
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

TIER1_INTERVAL_SEC = int(_os.getenv("NEWS_TIER1_INTERVAL_MIN", "15")) * 60
TIER2_INTERVAL_SEC = int(_os.getenv("NEWS_TIER2_INTERVAL_MIN", "60")) * 60

MAX_ARTICLES_PER_TICKER = int(_os.getenv("NEWS_MAX_PER_TICKER", "50"))
MAX_PER_TICKER_FEED = int(_os.getenv("NEWS_MAX_PER_TICKER_FEED", "3"))
