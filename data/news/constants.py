"""Shared constants for the news module."""

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

HOT_TICKERS_LIST = sorted(set(HOT_STOCKS + HOT_ETFS))
HOT_TICKERS_SET = frozenset(HOT_TICKERS_LIST)
