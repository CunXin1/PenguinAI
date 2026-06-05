"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Telescope, ArrowUpDown, Search } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { MOCK_UNIVERSE } from "@/lib/mock";
import { money, signedPct, cn } from "@/lib/utils";

const SECTORS = ["All", ...Array.from(new Set(MOCK_UNIVERSE.map((u) => u.sector)))];

type SortKey = "ticker" | "price" | "change_pct" | "confidence";

export default function ScreenerPage() {
  const [q, setQ] = useState("");
  const [sector, setSector] = useState("All");
  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [dir, setDir] = useState<"asc" | "desc">("desc");

  const rows = useMemo(() => {
    const filtered = MOCK_UNIVERSE.filter(
      (u) =>
        (sector === "All" || u.sector === sector) &&
        (q === "" || u.ticker.includes(q.toUpperCase()) || u.name.toLowerCase().includes(q.toLowerCase()))
    );
    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const cmp = typeof av === "string" ? String(av).localeCompare(String(bv)) : (av as number) - (bv as number);
      return dir === "asc" ? cmp : -cmp;
    });
  }, [q, sector, sortKey, dir]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setDir("desc");
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <Telescope size={20} className="text-sky-500 dark:text-sky-400" /> Stock Screener
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">Browse the signal universe · {MOCK_UNIVERSE.length} instruments</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 w-64 focus-within:border-sky-500/60 transition-colors">
          <Search size={14} className="text-zinc-500" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter ticker or name..."
            className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-full"
          />
        </div>
        <div className="flex gap-1 flex-wrap">
          {SECTORS.map((s) => (
            <button
              key={s}
              onClick={() => setSector(s)}
              className={cn(
                "px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
                sector === s
                  ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                  : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <Card className="overflow-hidden">
        <div className="grid grid-cols-12 gap-2 px-4 py-2.5 border-b border-zinc-200 dark:border-zinc-800 text-[11px] uppercase tracking-wider text-zinc-500">
          <button onClick={() => toggleSort("ticker")} className="col-span-4 sm:col-span-3 text-left flex items-center gap-1 hover:text-zinc-700 dark:hover:text-zinc-300">
            Symbol <ArrowUpDown size={11} />
          </button>
          <div className="hidden sm:block col-span-3">Sector</div>
          <button onClick={() => toggleSort("price")} className="col-span-3 sm:col-span-2 text-right flex items-center justify-end gap-1 hover:text-zinc-700 dark:hover:text-zinc-300">
            Price <ArrowUpDown size={11} />
          </button>
          <button onClick={() => toggleSort("change_pct")} className="col-span-2 text-right flex items-center justify-end gap-1 hover:text-zinc-700 dark:hover:text-zinc-300">
            24h <ArrowUpDown size={11} />
          </button>
          <button onClick={() => toggleSort("confidence")} className="col-span-3 sm:col-span-2 text-right flex items-center justify-end gap-1 hover:text-zinc-700 dark:hover:text-zinc-300">
            Signal <ArrowUpDown size={11} />
          </button>
        </div>

        <div className="divide-y divide-zinc-200 dark:divide-zinc-800/70">
          {rows.map((u) => (
            <Link
              key={u.ticker}
              href={`/signals/${u.ticker}`}
              className="grid grid-cols-12 gap-2 px-4 py-3 items-center hover:bg-zinc-100 dark:hover:bg-zinc-800/30 transition-colors"
            >
              <div className="col-span-4 sm:col-span-3 min-w-0">
                <p className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100">{u.ticker}</p>
                <p className="text-xs text-zinc-500 truncate">{u.name}</p>
              </div>
              <div className="hidden sm:block col-span-3 text-sm text-zinc-600 dark:text-zinc-400">{u.sector}</div>
              <div className="col-span-3 sm:col-span-2 text-right font-mono text-sm text-zinc-800 dark:text-zinc-200">{money(u.price)}</div>
              <div className={cn("col-span-2 text-right font-mono text-sm", u.change_pct >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
                {signedPct(u.change_pct, 1)}
              </div>
              <div className="col-span-3 sm:col-span-2 flex items-center justify-end gap-2">
                <span className="text-xs font-mono text-zinc-600 dark:text-zinc-400 hidden sm:inline">{Math.round(u.confidence * 100)}%</span>
                <DirectionBadge direction={u.direction} />
              </div>
            </Link>
          ))}
        </div>
      </Card>

      {rows.length === 0 && <p className="text-center text-sm text-zinc-400 dark:text-zinc-600 py-8">No matches for “{q}”.</p>}
    </div>
  );
}
