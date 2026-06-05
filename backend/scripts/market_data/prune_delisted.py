"""Move symbols that did NOT update to the latest date (delisted/stopped trading)
out of the active universe.

After a Yahoo refresh, an active symbol's last bar is the latest session; a symbol
that Yahoo has no recent data for (delisted, merged SPAC, halted) keeps its old last
bar. So 'delisted' = last_ts older than (global max for that asset type) - stale-days.

Default --report (no changes). --apply moves files to by_symbol/<asset>_delisted/
and rewrites the kept list.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import timedelta
from pathlib import Path

import pyarrow.parquet as pq


def last_ts(path: Path):
    t = pq.read_table(path, columns=["ts"])
    return max(t.column("ts").to_pylist()) if t.num_rows else None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--by-symbol-root", default=r"D:\BaiduNetdiskDownload\30min\30min_data")
    p.add_argument("--asset-type", choices=["stock", "etf", "all"], default="stock")
    p.add_argument("--stale-days", type=int, default=7)
    p.add_argument("--apply", action="store_true")
    return p.parse_args()


def prune_one(root: Path, at: str, stale_days: int, apply: bool) -> None:
    d = root / at
    files = sorted(d.glob("*.parquet"))
    lasts = {f: last_ts(f) for f in files}
    gmax = max(v for v in lasts.values() if v is not None)
    cutoff = gmax - timedelta(days=stale_days)
    stale = sorted(
        (f for f in files if lasts[f] is None or lasts[f] < cutoff), key=lambda f: lasts[f] or gmax
    )

    print(f"\n[{at}] files={len(files):,}  latest bar={gmax}  cutoff={cutoff} (-{stale_days}d)")
    print(f"  delisted/stale = {len(stale):,}")
    for f in stale:
        print(f"    {f.stem:10s} last={lasts[f]}")

    if not apply:
        return
    excl = root / f"{at}_delisted"
    excl.mkdir(parents=True, exist_ok=True)
    for f in stale:
        shutil.move(str(f), str(excl / f.name))
    kept = sorted(f.stem for f in d.glob("*.parquet"))
    (root / f"_universe_{at}_common.txt").write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(
        f"  applied: moved {len(stale):,} -> {excl} ; kept {len(kept):,} (rewrote _universe_{at}_common.txt)"
    )


def main() -> int:
    args = parse_args()
    root = Path(args.by_symbol_root)
    ats = ["stock", "etf"] if args.asset_type == "all" else [args.asset_type]
    for at in ats:
        prune_one(root, at, args.stale_days, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
