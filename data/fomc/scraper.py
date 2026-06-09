"""FOMC statement scraper — Federal Reserve website.

Discovers statement URLs from the FOMC calendars page (2021-present) and
historical-year pages (2000-2020), then downloads the full statement text
from each press release page.

No API key required. Self-throttled to ~2 req/s to stay well under any
informal rate limit.

RUN (standalone test):
    python -m data.fomc.scraper
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("fomc_scraper")

FED_BASE = "https://www.federalreserve.gov"
CALENDARS_URL = f"{FED_BASE}/monetarypolicy/fomccalendars.htm"
HISTORICAL_URL_TPL = f"{FED_BASE}/monetarypolicy/fomchistorical{{year}}.htm"

STATEMENT_LINK_RE = re.compile(
    r"/newsevents/pressreleases/monetary(\d{8})a\.htm"
)


@dataclass
class FomcStatementMeta:
    date: str  # YYYY-MM-DD
    url: str  # full URL to statement page


async def discover_statement_urls(
    client: httpx.AsyncClient,
    *,
    start_year: int = 2000,
    end_year: int | None = None,
) -> list[FomcStatementMeta]:
    """Scrape the Fed website for all FOMC statement links in the year range."""
    now_year = datetime.now().year
    if end_year is None:
        end_year = now_year

    seen: set[str] = set()
    results: list[FomcStatementMeta] = []

    pages_to_fetch: list[str] = [CALENDARS_URL]
    for year in range(start_year, min(end_year + 1, 2021)):
        pages_to_fetch.append(HISTORICAL_URL_TPL.format(year=year))

    for page_url in pages_to_fetch:
        try:
            resp = await client.get(page_url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("failed to fetch %s: %s", page_url, exc)
            continue

        for match in STATEMENT_LINK_RE.finditer(resp.text):
            path = match.group(0)
            date_str = match.group(1)
            year = int(date_str[:4])
            if year < start_year or year > end_year:
                continue
            if path in seen:
                continue
            seen.add(path)

            date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            results.append(FomcStatementMeta(
                date=date_fmt,
                url=f"{FED_BASE}{path}",
            ))

    results.sort(key=lambda s: s.date)
    logger.info("discovered %d FOMC statement URLs (%s — %s)", len(results), start_year, end_year)
    return results


async def fetch_statement_text(
    client: httpx.AsyncClient,
    url: str,
) -> str | None:
    """Download a single FOMC statement page and extract the body text."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("failed to fetch statement %s: %s", url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    article = (
        soup.find("div", id="article")
        or soup.find("div", class_="col-xs-12 col-sm-8 col-md-8")
        or soup.find("div", id="content")
    )
    if article is None:
        article = soup

    for tag in article.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    text = article.get_text(separator="\n", strip=True)

    lines = text.split("\n")
    body_lines: list[str] = []
    in_body = False
    skip_prefixes = ("share", "print", "subscribe", "last update", "page last updated")
    for line in lines:
        line_stripped = line.strip()
        if not in_body:
            if "federal open market committee" in line_stripped.lower():
                in_body = True
                continue
            if "for release" in line_stripped.lower() or "for immediate release" in line_stripped.lower():
                in_body = True
                continue
        if in_body:
            if line_stripped.lower().startswith("voting for"):
                break
            if line_stripped.lower().startswith("implementation note"):
                break
            if line_stripped.lower() in skip_prefixes:
                continue
            if line_stripped:
                body_lines.append(line_stripped)

    if body_lines:
        return "\n".join(body_lines)

    return text.strip() if text.strip() else None


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)

    async def _main():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            urls = await discover_statement_urls(client, start_year=2024)
            print(f"\n{len(urls)} statements found:")
            for s in urls:
                print(f"  {s.date}  {s.url}")
            if urls:
                txt = await fetch_statement_text(client, urls[-1].url)
                print(f"\nLatest statement preview ({urls[-1].date}):")
                print(txt[:500] if txt else "(empty)")

    asyncio.run(_main())
