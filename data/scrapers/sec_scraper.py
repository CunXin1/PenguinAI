"""
SEC EDGAR scraper: 13F filings (celebrity holdings) + FOMC statements.
Uses EDGAR's public JSON API — no auth required.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://data.sec.gov"
FED_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

# CIK numbers for tracked celebrities / funds
CELEBRITY_CIKS = {
    "berkshire_hathaway": "0001067983",  # Buffett
    "ark_invest":         "0001579982",  # Cathie Wood
}

HAWK_KEYWORDS = ["raise rates", "tighten", "inflationary", "above target", "restrictive"]
DOVE_KEYWORDS = ["lower rates", "accommodative", "below target", "support growth", "cut"]


class SECScraper:
    async def fetch_13f_holdings(self, cik: str, celebrity: str) -> list[dict]:
        """Fetch latest 13F filing for a given CIK and parse holdings."""
        url = f"{EDGAR_BASE}/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F-HR&dateb=&owner=include&count=1&search_text=&output=atom"
        async with httpx.AsyncClient(headers={"User-Agent": "PenguinAI contact@penguinai.com"}) as client:
            try:
                resp = await client.get(url, timeout=15)
                resp.raise_for_status()
                # Parse XML/JSON response for filing URL, then fetch holdings table
                # Full implementation: parse atom feed → get filing index → fetch infotable XML
                logger.info("13F fetched for %s (CIK: %s)", celebrity, cik)
                return []  # TODO: parse holdings from infotable
            except Exception as e:
                logger.error("13F fetch failed for %s: %s", celebrity, e)
                return []

    async def fetch_fomc_statement(self) -> dict | None:
        """Fetch latest FOMC statement and compute hawk/dove score."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    "https://www.federalreserve.gov/monetarypolicy/fomcminutes20250319.htm",
                    timeout=15,
                )
                text = resp.text
                hawk_score = self._score_hawk_dove(text)
                return {
                    "time": datetime.now(timezone.utc),
                    "document_url": resp.url,
                    "hawk_dove_score": hawk_score,
                    "summary": self._extract_summary(text),
                    "raw_text": text[:5000],
                }
            except Exception as e:
                logger.error("FOMC fetch failed: %s", e)
                return None

    def _score_hawk_dove(self, text: str) -> float:
        """Simple keyword-based hawk/dove scoring. Range: [-1, 1]."""
        text_lower = text.lower()
        hawk_count = sum(1 for kw in HAWK_KEYWORDS if kw in text_lower)
        dove_count = sum(1 for kw in DOVE_KEYWORDS if kw in text_lower)
        total = hawk_count + dove_count
        if total == 0:
            return 0.0
        return round((hawk_count - dove_count) / total, 4)

    def _extract_summary(self, html: str) -> str:
        """Extract first 500 chars of meaningful text from FOMC HTML."""
        clean = re.sub(r'<[^>]+>', ' ', html)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean[:500]


sec_scraper = SECScraper()
