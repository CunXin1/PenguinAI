"""Monitor the yahoo_fetch.py run: how many symbols succeeded / empty / errored.

Reads the fetch checkpoint (yahoo_staging/_checkpoint.jsonl, one JSON record per
symbol) and the universe size (by_symbol/{stock,etf}/*.parquet), then prints a live
tally. Re-run anytime, or use --watch N to refresh every N seconds.

Record meanings:
  ok     = rows > 0           (bars fetched & staged)
  empty  = rows == 0          (Yahoo returned nothing: delisted / unknown / symbol-map miss)
  error  = has an 'error'     (exception during fetch/convert)
Failures (empty+error) are written to yahoo_staging/_failures.txt for a retry pass.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import time
from datetime import datetime
from pathlib import Path


def count_universe(by_symbol_root: Path) -> dict[str, int]:
    out = {}
    for at in ("stock", "etf"):
        d = by_symbol_root / at
        out[at] = len(list(d.glob("*.parquet"))) if d.is_dir() else 0
    return out


def load_checkpoint(path: Path) -> dict[str, dict]:
    """key -> latest record (last line wins; tolerant of a half-written tail line)."""
    recs: dict[str, dict] = {}
    if not path.exists():
        return recs
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        k = r.get("key")
        if k:
            recs[k] = r
    return recs


def classify(r: dict) -> str:
    if r.get("error"):
        return "error"
    if r.get("rows", 0) > 0:
        return "ok"
    return "empty"


def report(args) -> None:
    by_symbol_root = Path(args.by_symbol_root)
    staging = Path(args.staging_dir)
    cp = Path(args.checkpoint) if args.checkpoint else staging / "_checkpoint.jsonl"

    universe = count_universe(by_symbol_root)
    total = sum(universe.values())
    recs = load_checkpoint(cp)

    tally = {"ok": 0, "empty": 0, "error": 0}
    per_at = {"stock": {"ok": 0, "empty": 0, "error": 0}, "etf": {"ok": 0, "empty": 0, "error": 0}}
    residual = 0
    newest = ""
    failures: list[tuple[str, str]] = []
    for k, r in recs.items():
        cls = classify(r)
        tally[cls] += 1
        at = k.split("/", 1)[0]
        if at in per_at:
            per_at[at][cls] += 1
        if r.get("residual_gap"):
            residual += 1
        last = r.get("last") or ""
        if last and last > newest:
            newest = last
        if cls != "ok":
            failures.append((k, r.get("error") or r.get("note") or "empty"))

    processed = len(recs)
    pct = processed / total * 100 if total else 0
    mtime = (
        datetime.fromtimestamp(cp.stat().st_mtime).strftime("%H:%M:%S") if cp.exists() else "n/a"
    )

    print(f"== Yahoo fetch monitor @ {datetime.now():%H:%M:%S}  (checkpoint last write {mtime}) ==")
    print(f"checkpoint: {cp}")
    print(
        f"processed: {processed:,} / {total:,} ({pct:.1f}%)   "
        f"ok={tally['ok']:,}  empty={tally['empty']:,}  error={tally['error']:,}"
    )
    for at in ("stock", "etf"):
        p = per_at[at]
        print(
            f"  {at:5s}: {sum(p.values()):,}/{universe[at]:,}  "
            f"ok={p['ok']:,}  empty={p['empty']:,}  error={p['error']:,}"
        )
    print(f"residual_gap (last bar older than fetch window): {residual:,}")
    print(f"newest staged bar: {newest or 'n/a'}")
    if failures:
        failures.sort()
        fp = staging / "_failures.txt"
        with contextlib.suppress(Exception):
            fp.write_text("\n".join(k for k, _ in failures) + "\n", encoding="utf-8")
        print(f"\nfailures (empty/error): {len(failures):,}  -> wrote {fp}")
        for k, why in failures[:30]:
            print(f"  {k}: {why}")
        if len(failures) > 30:
            print(f"  ... (+{len(failures) - 30:,} more in _failures.txt)")
    if processed >= total:
        print("\n** all symbols processed **")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Monitor yahoo_fetch progress.")
    p.add_argument("--by-symbol-root", default=r"D:\BaiduNetdiskDownload\30min\30min_data")
    p.add_argument("--staging-dir", default=r"D:\BaiduNetdiskDownload\30min\yahoo_staging")
    p.add_argument("--checkpoint", default=None)
    p.add_argument("--watch", type=float, default=0, help="Refresh every N seconds (0 = once).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.watch > 0:
        try:
            while True:
                print("\033[2J\033[H", end="")  # clear screen
                report(args)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            pass
    else:
        report(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
