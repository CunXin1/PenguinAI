"""Map SIC codes (from Massive ticker details) to investing-friendly sectors.

Massive's per-ticker details endpoint (``/v3/reference/tickers/{sym}``) returns
``sic_code`` + ``sic_description``. We already call it for market cap, so this
costs no extra requests. We store the description verbatim as ``tickers.industry``
and bucket the numeric code into a coarse ``tickers.sector`` for the heatmap /
screener (which previously only had ~36 hand-maintained sector rows and an
always-empty ``industry`` column).

SIC reference: https://www.sec.gov/info/edgar/siccodes.htm

The mapping is intentionally coarse — the 2-digit major group drives the sector,
with a handful of 4-digit / 3-digit overrides where a major group spans several
investing sectors (pharma sits under Chemicals, software under Business Services,
biotech under Research labs, REITs under Holding companies, etc.).
"""

from __future__ import annotations

# 4-digit exact overrides (checked first — highest precedence).
_SIC4: dict[str, str] = {
    "2833": "Healthcare",  # medicinal chemicals
    "2834": "Healthcare",  # pharmaceutical preparations
    "2835": "Healthcare",  # in-vitro / in-vivo diagnostics
    "2836": "Healthcare",  # biological products
    "3674": "Technology",  # semiconductors
    "3711": "Consumer Discretionary",  # motor vehicles
    "3713": "Consumer Discretionary",  # truck & bus bodies
    "3714": "Consumer Discretionary",  # motor vehicle parts
    "3716": "Consumer Discretionary",  # motor homes
    "3721": "Industrials",  # aircraft
    "3724": "Industrials",  # aircraft engines
    "3728": "Industrials",  # aircraft parts
    "3760": "Industrials",  # guided missiles & space vehicles
    "3761": "Industrials",  # guided missiles
    "3812": "Industrials",  # search, detection, navigation (defense)
    "6798": "Real Estate",  # REIT
    "8731": "Healthcare",  # commercial physical & biological research (biotech)
}

# 3-digit prefix overrides (checked after 4-digit).
_SIC3: dict[str, str] = {
    "283": "Healthcare",  # drugs
    "357": "Technology",  # computer & office equipment
    "384": "Healthcare",  # surgical & medical instruments
    "385": "Healthcare",  # ophthalmic goods
    "372": "Industrials",  # aircraft & parts
    "376": "Industrials",  # guided missiles & space
    "731": "Communication Services",  # advertising
}

# 2-digit major group → sector (the default bucket).
_SIC2: dict[str, str] = {
    "01": "Agriculture", "02": "Agriculture", "07": "Agriculture", "08": "Agriculture",
    "09": "Agriculture",
    "10": "Materials", "12": "Energy", "13": "Energy", "14": "Materials",
    "15": "Industrials", "16": "Industrials", "17": "Industrials",
    "20": "Consumer Staples", "21": "Consumer Staples",
    "22": "Consumer Discretionary", "23": "Consumer Discretionary",
    "24": "Industrials", "25": "Consumer Discretionary", "26": "Materials",
    "27": "Communication Services", "28": "Materials", "29": "Energy",
    "30": "Materials", "31": "Consumer Discretionary", "32": "Materials",
    "33": "Materials", "34": "Industrials", "35": "Industrials", "36": "Technology",
    "37": "Consumer Discretionary", "38": "Technology", "39": "Consumer Discretionary",
    "40": "Industrials", "41": "Industrials", "42": "Industrials", "43": "Industrials",
    "44": "Industrials", "45": "Industrials", "46": "Industrials", "47": "Industrials",
    "48": "Communication Services", "49": "Utilities",
    "50": "Industrials", "51": "Industrials",
    "52": "Consumer Discretionary", "53": "Consumer Discretionary",
    "54": "Consumer Staples", "55": "Consumer Discretionary", "56": "Consumer Discretionary",
    "57": "Consumer Discretionary", "58": "Consumer Discretionary", "59": "Consumer Discretionary",
    "60": "Financials", "61": "Financials", "62": "Financials", "63": "Financials",
    "64": "Financials", "65": "Real Estate", "67": "Financials",
    "70": "Consumer Discretionary", "72": "Consumer Discretionary", "73": "Technology",
    "75": "Consumer Discretionary", "78": "Communication Services",
    "79": "Communication Services", "80": "Healthcare", "82": "Consumer Discretionary",
    "87": "Industrials",
}


def sic_to_sector(sic_code: str | int | None) -> str | None:
    """Bucket a SIC code into a coarse investing sector. None if unmappable."""
    if sic_code is None:
        return None
    code = str(sic_code).strip()
    if not code.isdigit():
        return None
    code = code.zfill(4)[:4]
    if code in _SIC4:
        return _SIC4[code]
    if code[:3] in _SIC3:
        return _SIC3[code[:3]]
    return _SIC2.get(code[:2])
