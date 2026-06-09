"""SEC EDGAR 13F filings → ``celebrity_holdings`` table ingestion.

Free, no API key. Parses quarterly 13F-HR filings for a curated list of
institutional investors (Buffett, Soros, Dalio, Ackman) and computes
BUY/SELL/HOLD actions by diffing the current quarter against the prior one.

SEC EDGAR requires a descriptive User-Agent header with a contact email.
Rate limit: 10 requests/second (we self-throttle to ~7 req/s).

RUN (from repo root, with .env present and Postgres up):
    python -m data.celebrity.sec_13f
    make fetch-13f
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("celebrity_13f")

FILERS_13F: dict[str, str] = {
    "0001067983": "buffett",
    "0001029160": "soros",
    "0001336528": "dalio",
    "0001649339": "ackman",
}

# Well-known CUSIPs → tickers (top holdings that appear across these filers).
CUSIP_MAP: dict[str, str] = {
    "037833100": "AAPL",
    "594918104": "MSFT",
    "023135106": "AMZN",
    "02079K305": "GOOGL",
    "02079K107": "GOOG",
    "30303M102": "META",
    "67066G104": "NVDA",
    "88160R101": "TSLA",
    "084670702": "BRK.B",
    "060505104": "BAC",
    "17275R102": "CSCO",
    "46625H100": "JPM",
    "742718109": "PG",
    "478160104": "JNJ",
    "91324P102": "UNH",
    "20825C104": "KO",
    "172967424": "C",
    "931142103": "WMT",
    "571748102": "MA",
    "92826C839": "V",
    "22160K105": "COST",
    "002824100": "ABBV",
    "532457108": "LLY",
    "78462F103": "SPY",
    "46090E103": "QQQ",
    "084670108": "BRK.A",
    "126650100": "CVX",
    "345370860": "F",
    "369604301": "GE",
    "58933Y105": "MRK",
    "693475105": "PFE",
    "87612E106": "TMUS",
    "00206R102": "T",
    "032654105": "AMGN",
    "256135203": "DG",
}

_UNIVERSE_SQL = text("SELECT ticker FROM tickers")
_UPSERT_SQL = text("""
    INSERT INTO celebrity_holdings
        (reported_at, celebrity, ticker, action, shares, value_usd, source_type, filing_url)
    VALUES
        (:reported_at, :celebrity, :ticker, :action, :shares, :value_usd, :source_type, :filing_url)
    ON CONFLICT (celebrity, ticker, reported_at, action) DO UPDATE SET
        shares    = EXCLUDED.shares,
        value_usd = EXCLUDED.value_usd,
        filing_url = EXCLUDED.filing_url
""")

SEC_BASE = "https://data.sec.gov"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


class LoaderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    DATABASE_URL: str = "postgresql+asyncpg://penguinai:penguinai_dev@localhost:5432/penguinai"
    SEC_USER_AGENT: str = "PenguinAI/0.1 sunruibo5@gmail.com"


def _pad_cik(cik: str) -> str:
    return cik.lstrip("0").zfill(10)


async def _fetch_submissions(client: httpx.AsyncClient, cik: str) -> dict:
    padded = _pad_cik(cik)
    url = f"{SEC_BASE}/submissions/CIK{padded}.json"
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.json()


def _find_13f_filings(submissions: dict, max_filings: int = 2) -> list[dict]:
    """Extract the most recent 13F-HR filing accession numbers."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    filings = []
    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A") and i < len(accessions):
            filings.append({
                "accession": accessions[i],
                "filing_date": dates[i] if i < len(dates) else None,
                "primary_doc": primary_docs[i] if i < len(primary_docs) else None,
            })
            if len(filings) >= max_filings:
                break
    return filings


async def _fetch_infotable(
    client: httpx.AsyncClient, cik: str, accession: str
) -> list[dict]:
    """Download and parse the 13F XML infotable."""
    cik_num = cik.lstrip("0")
    acc_nodash = accession.replace("-", "")

    # Try common infotable filenames first
    for filename in ("infotable.xml", "InfoTable.xml"):
        url = f"{SEC_ARCHIVES}/{cik_num}/{acc_nodash}/{filename}"
        resp = await client.get(url)
        if resp.status_code == 200:
            result = _parse_infotable_xml(resp.text)
            if result:
                return result
        await asyncio.sleep(0.15)

    # Fallback: fetch the filing index and try all non-primary XML files
    index_url = f"{SEC_ARCHIVES}/{cik_num}/{acc_nodash}/index.json"
    resp = await client.get(index_url)
    if resp.status_code == 200:
        await asyncio.sleep(0.15)
        index_data = resp.json()
        for item in index_data.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if not name.lower().endswith(".xml") or name.lower() == "primary_doc.xml":
                continue
            url = f"{SEC_ARCHIVES}/{cik_num}/{acc_nodash}/{name}"
            resp = await client.get(url)
            if resp.status_code == 200:
                result = _parse_infotable_xml(resp.text)
                if result:
                    return result
            await asyncio.sleep(0.15)

    logger.warning("  could not find infotable for accession %s", accession)
    return []


def _parse_infotable_xml(xml_text: str) -> list[dict]:
    """Parse 13F infotable XML into a list of holdings."""
    holdings = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("  XML parse error: %s", exc)
        return []

    ns = ""
    for elem in root.iter():
        tag = elem.tag
        if "}" in tag:
            ns = tag[: tag.index("}") + 1]
            break

    for info in root.iter(f"{ns}infoTable"):
        cusip_el = info.find(f"{ns}cusip")
        name_el = info.find(f"{ns}nameOfIssuer")
        value_el = info.find(f"{ns}value")
        shares_el = info.find(f".//{ns}sshPrnamt")

        cusip = (cusip_el.text or "").strip() if cusip_el is not None else ""
        name = (name_el.text or "").strip() if name_el is not None else ""

        try:
            value_thousands = int(value_el.text) if value_el is not None and value_el.text else 0
        except ValueError:
            value_thousands = 0

        try:
            shares = int(shares_el.text) if shares_el is not None and shares_el.text else 0
        except ValueError:
            shares = 0

        if cusip or name:
            holdings.append({
                "cusip": cusip,
                "name": name,
                "value_usd": value_thousands * 1000,
                "shares": shares,
            })

    return holdings


def _cusip_to_ticker(cusip: str, name: str, universe: set[str], name_map: dict[str, str]) -> str | None:
    if cusip in CUSIP_MAP:
        ticker = CUSIP_MAP[cusip]
        return ticker if ticker in universe else None

    name_upper = name.upper().strip()
    if name_upper in name_map:
        return name_map[name_upper]

    # Require at least 2 leading words to match to avoid false positives
    # (e.g. "APPLE INC" matches "APPLE INC" but not "APPLE HOSPITALITY REIT")
    words = name_upper.split()
    if len(words) >= 2:
        prefix = f"{words[0]} {words[1]}"
        candidates = [(k, v) for k, v in name_map.items() if k.startswith(prefix)]
        if len(candidates) == 1:
            return candidates[0][1]

    return None


def _diff_quarters(
    current: dict[str, dict],
    prior: dict[str, dict],
) -> list[dict]:
    """Compare two quarter snapshots. Returns action entries (BUY/SELL/HOLD)."""
    actions = []
    all_tickers = set(current.keys()) | set(prior.keys())

    for ticker in all_tickers:
        cur = current.get(ticker)
        prev = prior.get(ticker)

        if cur and not prev:
            actions.append({**cur, "action": "BUY"})
        elif cur and prev:
            if cur["shares"] > prev["shares"]:
                actions.append({**cur, "action": "BUY"})
            elif cur["shares"] < prev["shares"]:
                actions.append({**cur, "action": "SELL"})
            else:
                actions.append({**cur, "action": "HOLD"})
        elif prev and not cur:
            actions.append({**prev, "action": "SELL", "shares": 0, "value_usd": 0})

    return actions


async def run_loader(database_url: str, user_agent: str) -> int:
    engine = create_async_engine(database_url)
    try:
        universe = set()
        name_map: dict[str, str] = {}
        async with engine.connect() as conn:
            result = await conn.execute(_UNIVERSE_SQL)
            universe = {row[0] for row in result}
            result2 = await conn.execute(text("SELECT UPPER(name), ticker FROM tickers WHERE name IS NOT NULL"))
            name_map = {row[0]: row[1] for row in result2}

        if not universe:
            logger.warning("tickers table is empty — run bootstrap_universe.py first")
            return 0
        logger.info("universe: %d known tickers, %d name mappings", len(universe), len(name_map))

        all_rows: list[dict] = []
        headers = {"User-Agent": user_agent}

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            for cik, celeb_slug in FILERS_13F.items():
                logger.info("processing %s (CIK %s)...", celeb_slug, cik)
                await asyncio.sleep(0.15)

                try:
                    subs = await _fetch_submissions(client, cik)
                except Exception as exc:
                    logger.warning("  submissions fetch failed: %s", exc)
                    continue

                filings = _find_13f_filings(subs, max_filings=2)
                if not filings:
                    logger.warning("  no 13F-HR filings found")
                    continue

                logger.info("  found %d 13F filings", len(filings))

                snapshots: list[tuple[str | None, dict[str, dict]]] = []
                for filing in filings:
                    await asyncio.sleep(0.15)
                    holdings = await _fetch_infotable(client, cik, filing["accession"])
                    logger.info(
                        "  filing %s (%s): %d holdings",
                        filing["accession"],
                        filing["filing_date"],
                        len(holdings),
                    )

                    snapshot: dict[str, dict] = {}
                    for h in holdings:
                        ticker = _cusip_to_ticker(h["cusip"], h["name"], universe, name_map)
                        if ticker:
                            if ticker in snapshot:
                                snapshot[ticker]["shares"] += h["shares"]
                                snapshot[ticker]["value_usd"] += h["value_usd"]
                            else:
                                snapshot[ticker] = {
                                    "ticker": ticker,
                                    "shares": h["shares"],
                                    "value_usd": h["value_usd"],
                                }

                    snapshots.append((filing["filing_date"], snapshot))

                if len(snapshots) >= 2:
                    current_date, current_snap = snapshots[0]
                    _, prior_snap = snapshots[1]
                    actions = _diff_quarters(current_snap, prior_snap)
                elif len(snapshots) == 1:
                    current_date, current_snap = snapshots[0]
                    actions = [
                        {**v, "action": "HOLD"} for v in current_snap.values()
                    ]
                else:
                    continue

                filing_date = None
                if current_date:
                    try:
                        filing_date = datetime.strptime(current_date, "%Y-%m-%d").replace(tzinfo=UTC)
                    except ValueError:
                        filing_date = datetime.now(UTC)
                else:
                    filing_date = datetime.now(UTC)

                filing_url = (
                    f"https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&CIK={cik}&type=13F-HR&dateb=&owner=include&count=1"
                )

                for act in actions:
                    all_rows.append({
                        "reported_at": filing_date,
                        "celebrity": celeb_slug,
                        "ticker": act["ticker"],
                        "action": act["action"],
                        "shares": act.get("shares"),
                        "value_usd": act.get("value_usd"),
                        "source_type": "13F",
                        "filing_url": filing_url,
                    })

        if not all_rows:
            logger.info("no rows to upsert")
            return 0

        deduped: dict[tuple, dict] = {}
        for r in all_rows:
            key = (r["celebrity"], r["ticker"], r["reported_at"], r["action"])
            deduped[key] = r
        rows = list(deduped.values())

        written = 0
        for i in range(0, len(rows), 500):
            batch = rows[i : i + 500]
            async with engine.begin() as conn:
                await conn.execute(_UPSERT_SQL, batch)
            written += len(batch)

        buys = sum(1 for r in rows if r["action"] == "BUY")
        sells = sum(1 for r in rows if r["action"] == "SELL")
        holds = sum(1 for r in rows if r["action"] == "HOLD")
        logger.info("upserted %d 13F holdings (%d BUY, %d SELL, %d HOLD)", written, buys, sells, holds)
        return written
    finally:
        await engine.dispose()


async def run_default() -> int:
    s = LoaderSettings()
    return await run_loader(s.DATABASE_URL, s.SEC_USER_AGENT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load SEC EDGAR 13F filings into celebrity_holdings.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    parser.add_argument("--user-agent", default=None, help="Override SEC User-Agent header.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    s = LoaderSettings()
    db_url = args.database_url or s.DATABASE_URL
    ua = args.user_agent or s.SEC_USER_AGENT
    logger.info("SEC EDGAR 13F → celebrity_holdings")
    try:
        asyncio.run(run_loader(db_url, ua))
    except KeyboardInterrupt:
        logger.info("interrupted")


if __name__ == "__main__":
    main()
