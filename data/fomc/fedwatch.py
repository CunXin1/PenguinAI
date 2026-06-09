"""
CME FedWatch rate probability fetcher.

Scrapes the CME Group FedWatch tool page to extract market-implied
probabilities for each target rate level at the next FOMC meeting.
Returns a list of {meeting_date, target_rate_low, target_rate_high, probability}.
"""

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_FEDWATCH_URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
_TIMEOUT = 15.0
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def fetch_fedwatch_probabilities() -> list[dict] | None:
    """Fetch CME FedWatch probabilities for the next FOMC meeting.

    Attempts to scrape the CME FedWatch page and extract the probability
    data embedded in the page content. Falls back to returning None on
    any failure (transient or structural).
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS
        ) as client:
            resp = await client.get(_FEDWATCH_URL)
            if resp.status_code != 200:
                logger.warning("CME FedWatch returned %d", resp.status_code)
                return None

            return _parse_fedwatch_page(resp.text)

    except Exception:
        logger.warning("CME FedWatch fetch failed", exc_info=True)
        return None


def _parse_fedwatch_page(html: str) -> list[dict] | None:
    """Extract probability data from the CME FedWatch HTML.

    The page embeds JSON-like data with probability distributions.
    This parser looks for structured probability entries and extracts them.
    """
    probabilities = []

    pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(?:bps|%).*?"
        r"(\d+(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    )

    matches = pattern.findall(html)
    if matches:
        for low, high, prob in matches[:10]:
            try:
                probabilities.append({
                    "meeting_date": None,
                    "target_rate_low": float(low),
                    "target_rate_high": float(high),
                    "probability": float(prob),
                })
            except (ValueError, TypeError):
                continue

    if not probabilities:
        logger.info("CME FedWatch: no probability data extracted from page")
        return None

    total = sum(p["probability"] for p in probabilities)
    if total > 0 and abs(total - 100.0) > 5.0:
        for p in probabilities:
            p["probability"] = round(p["probability"] / total * 100, 2)

    probabilities.sort(key=lambda x: x["probability"], reverse=True)
    return probabilities


if __name__ == "__main__":
    import asyncio

    async def main():
        result = await fetch_fedwatch_probabilities()
        if result:
            print(f"Found {len(result)} rate probability entries:")
            for p in result:
                print(
                    f"  {p['target_rate_low']:.2f}–{p['target_rate_high']:.2f}%: "
                    f"{p['probability']:.1f}%"
                )
        else:
            print("No data returned")

    asyncio.run(main())
