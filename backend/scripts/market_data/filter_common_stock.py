"""Classify the STOCK universe by security type (NASDAQ Trader symbol directory)
and drop non-common-stock instruments: preferred shares, warrants, rights, SPAC
units, test issues. Dual-class common (BRK.B, HEI.A) and ADRs are KEPT.

Source of truth (free, authoritative):
  https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt
  https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt
The `Security Name` field names the instrument ("... Preferred Stock", "- Units",
"- Rights", "Warrant"). Symbols are matched by normalizing separators (the dataset
uses '.', NASDAQ uses '$' in ACT symbols and '-' in NASDAQ symbols) to '.'.

Default is --report (no file changes). Pass --apply to move dropped files from
by_symbol/stock to by_symbol/stock_noncommon and rewrite the universe manifest.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import urllib.request
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_by_symbol import safe_filename

NASDAQ_URLS = {
    "nasdaqlisted": "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
    "otherlisted": "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt",
}


def norm(sym: str) -> str:
    return re.sub(r"[ .\-$]+", ".", sym.strip().upper())


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("latin-1")


def load_directory(cache_dir: Path, refresh: bool) -> dict[str, dict]:
    """normalized symbol -> {name, etf, test}. Indexes every symbol column present."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    table: dict[str, dict] = {}
    for tag, url in NASDAQ_URLS.items():
        cache = cache_dir / f"{tag}.txt"
        if refresh or not cache.exists():
            cache.write_text(fetch_text(url), encoding="latin-1")
            print(f"  downloaded {tag} -> {cache}")
        lines = cache.read_text(encoding="latin-1").splitlines()
        header = lines[0].split("|")
        idx = {h: i for i, h in enumerate(header)}
        sym_cols = [c for c in ("Symbol", "ACT Symbol", "CQS Symbol", "NASDAQ Symbol") if c in idx]
        name_col = idx["Security Name"]
        etf_col = idx.get("ETF")
        test_col = idx.get("Test Issue")
        for ln in lines[1:]:
            if ln.startswith("File Creation Time"):
                continue
            f = ln.split("|")
            if len(f) <= name_col:
                continue
            rec = {
                "name": f[name_col],
                "etf": (f[etf_col] if etf_col is not None and etf_col < len(f) else ""),
                "test": (f[test_col] if test_col is not None and test_col < len(f) else ""),
            }
            for c in sym_cols:
                v = f[idx[c]].strip()
                if v:
                    table.setdefault(norm(v), rec)
    return table


def classify(symbol: str, name: str, etf: str, test: str) -> str:
    low = (name or "").lower()
    if test == "Y":
        return "test"
    if etf == "Y":
        return "etf"
    # Funds/trusts that merely mention 'preferred/income' are tradable common shares
    is_fund = bool(re.search(r"\bfund\b|\bclosed[- ]end\b", low))
    dotted = "." in symbol
    # Preferred signals: the word/abbrev, OR a *domestic* 'Depositary Shares' (NOT a
    # foreign 'American Depositary' ADR), OR a dotted ticker whose name reads like a
    # preferred series (handles truncated/abbreviated names: 'Dep Shs', 'Prd', '6.95% Series F').
    is_adr = bool(re.search(r"american deposit|\badr\b|\bads\b", low))
    pref_word = bool(re.search(r"\bpreferred\b|\bpfd\b|\bprd\b", low))
    domestic_dep = (
        bool(re.search(r"depositary shares?|\bdep sh", low))
        and not is_adr
        and not re.search(r"\bunits?\b|l\.?p\.?|\bpartners\b", low)
    )
    pref_series = dotted and bool(
        re.search(r"\bseries\s+[a-z]\b|%|cumulative|redeemable|fltg|fixed to fl", low)
    )
    if (pref_word or domestic_dep or pref_series) and not is_fund:
        return "preferred"
    # Foreign ADR/depositary common (preferred cases already returned above). Must run
    # before right/unit so ADR boilerplate ("the right to receive N units") isn't misread.
    if is_adr:
        return "common"
    if re.search(r"\bwarrant", low):
        return "warrant"
    # Exchange-traded debt ('baby bonds'): notes/debentures, not common stock
    if re.search(r"\bdebentures?\b|notes?\s+due|\bsubordinated notes?\b", low):
        return "note"
    # Rights only as the instrument designation (suffix), not "right to receive"
    if re.search(r"-\s*rights?\b|\bsubscription rights?\b|\brights?\s*$", low):
        return "right"
    # SPAC units (suffix) vs L.P./partnership/fund/trust units (keep as common-equivalent)
    if re.search(r"-\s*units?\b|\bunits?\s*$", low) and not re.search(
        r"l\.?p\.?|partners|partnership|\btrust\b|\bfund\b", low
    ):
        return "unit"
    return "common"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--by-symbol-root", default=r"D:\BaiduNetdiskDownload\30min\30min_data")
    p.add_argument("--cache-dir", default=r"D:\BaiduNetdiskDownload\30min\30min_data\_nasdaq")
    p.add_argument("--refresh", action="store_true", help="Re-download the NASDAQ files.")
    p.add_argument("--apply", action="store_true", help="Move dropped files + rewrite manifest.")
    p.add_argument(
        "--drop",
        default="preferred,warrant,right,unit,note,test,etf",
        help="Comma list of categories to exclude.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.by_symbol_root)
    drop_cats = {c.strip() for c in args.drop.split(",") if c.strip()}

    directory = load_directory(Path(args.cache_dir), args.refresh)
    print(f"NASDAQ directory: {len(directory):,} symbols indexed")

    man = pq.read_table(root / "_universe_stock.parquet")
    in_univ = man.filter(pc.field("in_universe"))
    syms = in_univ.column("symbol").to_pylist()

    cats: dict[str, list[str]] = {}
    sym_cat: dict[str, str] = {}
    for s in syms:
        rec = directory.get(norm(s))
        if rec is None:
            cat = "unmatched"
        else:
            cat = classify(s, rec["name"], rec["etf"], rec["test"])
        sym_cat[s] = cat
        cats.setdefault(cat, []).append(s)

    print(f"\nuniverse stocks = {len(syms):,}")
    for cat in sorted(cats, key=lambda c: -len(cats[c])):
        mark = "  DROP" if cat in drop_cats else "  keep"
        print(f"  {cat:10s} {len(cats[cat]):>5,}{mark}")

    dropped = sorted(s for s, c in sym_cat.items() if c in drop_cats)
    print(f"\n=> would DROP {len(dropped):,} ; KEEP {len(syms) - len(dropped):,}")
    for cat in ("preferred", "warrant", "right", "unit", "note", "etf", "test"):
        if cat in drop_cats and cats.get(cat):
            sample = cats[cat][:25]
            print(
                f"  {cat} ({len(cats[cat])}): {', '.join(sample)}"
                + (" ..." if len(cats[cat]) > 25 else "")
            )
    if cats.get("unmatched"):
        print(
            f"  UNMATCHED ({len(cats['unmatched'])}, kept, review): {', '.join(cats['unmatched'][:40])}"
            + (" ..." if len(cats["unmatched"]) > 40 else "")
        )

    # write a classification report parquet alongside the manifest
    rep = pa.table({"symbol": list(sym_cat), "security_type": [sym_cat[s] for s in sym_cat]})
    pq.write_table(rep, root / "_security_type_stock.parquet", compression="zstd")
    print(f"\nwrote classification -> {root / '_security_type_stock.parquet'}")

    if not args.apply:
        print("\nreport only (no files moved). Re-run with --apply to exclude the DROP set.")
        return 0

    excl = root / "stock_noncommon"
    excl.mkdir(parents=True, exist_ok=True)
    moved = 0
    drop_files = {f"{safe_filename(s)}.parquet" for s in dropped}
    for f in (root / "stock").glob("*.parquet"):
        if f.name in drop_files:
            shutil.move(str(f), str(excl / f.name))
            moved += 1
    keep = sorted(s for s in syms if sym_cat[s] not in drop_cats)
    (root / "_universe_stock_common.txt").write_text("\n".join(keep) + "\n", encoding="utf-8")
    print(f"applied: moved {moved:,} files -> {excl}")
    print(f"wrote _universe_stock_common.txt ({len(keep):,} common stocks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
