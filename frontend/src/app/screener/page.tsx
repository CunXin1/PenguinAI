"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Telescope, ArrowUpDown, Search, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { tickers as tickerApi } from "@/lib/api";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";
import { compact, money, signedPct, cn } from "@/lib/utils";
import type { Ticker, TickerSearchResult } from "@/lib/types";

interface Row {
  ticker: string;
  name: string;
  sector: string | null;
  market_cap: number | null;
}
type SortKey = "ticker" | "market_cap" | "change_pct";

export default function ScreenerPage() {
  const [q, setQ] = useState("");
  const [sector, setSector] = useState("All");
  const [sortKey, setSortKey] = useState<SortKey>("market_cap");
  const [dir, setDir] = useState<"asc" | "desc">("desc");

  // Top 500 by market cap — the screener landing set.
  const universeQ = useQuery<Ticker[]>({
    queryKey: ["universe", 500],
    queryFn: () => tickerApi.getUniverse(0, 500),
    staleTime: 60 * 60_000,
  });
  const universe = useMemo(() => universeQ.data ?? [], [universeQ.data]);

  // Typing searches the *whole* universe server-side (not just the loaded 500).
  const query = q.trim();
  const searchQ = useQuery<TickerSearchResult[]>({
    queryKey: ["ticker-search", query.toUpperCase()],
    queryFn: () => tickerApi.search(query),
    enabled: query.length >= 1,
    staleTime: 5 * 60_000,
  });

  // Overlay live prices for the most liquid names (those with minute data).
  const top60 = useMemo(() => universe.slice(0, 60).map((u) => u.ticker), [universe]);
  const { data: quotes } = useLiveQuotes(top60);

  const SECTORS = useMemo(() => {
    const s = new Set<string>();
    universe.forEach((u) => u.sector && s.add(u.sector));
    return ["All", ...Array.from(s).sort()];
  }, [universe]);

  const source: Row[] = useMemo(() => {
    if (query.length >= 1) {
      return (searchQ.data ?? []).map((r) => ({
        ticker: r.ticker,
        name: r.name,
        sector: r.sector,
        market_cap: null,
      }));
    }
    return universe.map((u) => ({
      ticker: u.ticker,
      name: u.name,
      sector: u.sector,
      market_cap: u.market_cap,
    }));
  }, [query, searchQ.data, universe]);

  const rows = useMemo(() => {
    const filtered = source.filter((u) => sector === "All" || u.sector === sector);
    const val = (r: Row): number | string => {
      if (sortKey === "ticker") return r.ticker;
      if (sortKey === "change_pct") return quotes[r.ticker]?.change_pct ?? -Infinity;
      return r.market_cap ?? -Infinity;
    };
    return [...filtered].sort((a, b) => {
      const av = val(a);
      const bv = val(b);
      const cmp =
        typeof av === "string" ? av.localeCompare(bv as string) : (av as number) - (bv as number);
      return dir === "asc" ? cmp : -cmp;
    });
  }, [source, sector, sortKey, dir, quotes]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setDir(k === "ticker" ? "asc" : "desc");
    }
  };

  const loading = query.length >= 1 ? searchQ.isLoading : universeQ.isLoading;

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <Telescope size={20} className="text-sky-500 dark:text-sky-400" /> Stock Screener
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          Top {universe.length} by market cap · search any ticker in the universe
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 w-64 focus-within:border-sky-500/60 transition-colors">
          <Search size={14} className="text-zinc-500" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search ticker or name..."
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
          <button
            onClick={() => toggleSort("ticker")}
            className="col-span-5 sm:col-span-4 text-left flex items-center gap-1 hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            Symbol <ArrowUpDown size={11} />
          </button>
          <div className="hidden sm:block col-span-3">Sector</div>
          <button
            onClick={() => toggleSort("market_cap")}
            className="col-span-4 sm:col-span-3 text-right flex items-center justify-end gap-1 hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            Mkt Cap <ArrowUpDown size={11} />
          </button>
          <button
            onClick={() => toggleSort("change_pct")}
            className="col-span-3 sm:col-span-2 text-right flex items-center justify-end gap-1 hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            Price <ArrowUpDown size={11} />
          </button>
        </div>

        {loading ? (
          <div className="py-16 grid place-items-center">
            <Loader2 size={20} className="animate-spin text-sky-500" />
          </div>
        ) : (
          <div className="divide-y divide-zinc-200 dark:divide-zinc-800/70">
            {rows.map((u) => {
              const qd = quotes[u.ticker];
              const up = (qd?.change_pct ?? 0) >= 0;
              return (
                <Link
                  key={u.ticker}
                  href={`/signals/${u.ticker}`}
                  className="grid grid-cols-12 gap-2 px-4 py-3 items-center hover:bg-zinc-100 dark:hover:bg-zinc-800/30 transition-colors"
                >
                  <div className="col-span-5 sm:col-span-4 min-w-0">
                    <p className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                      {u.ticker}
                    </p>
                    <p className="text-xs text-zinc-500 truncate">{u.name}</p>
                  </div>
                  <div className="hidden sm:block col-span-3 text-sm text-zinc-600 dark:text-zinc-400 truncate">
                    {u.sector ?? "—"}
                  </div>
                  <div className="col-span-4 sm:col-span-3 text-right font-mono text-sm text-zinc-800 dark:text-zinc-200">
                    {u.market_cap ? `$${compact(u.market_cap)}` : "—"}
                  </div>
                  <div className="col-span-3 sm:col-span-2 text-right">
                    {qd ? (
                      <>
                        <p className="font-mono text-sm text-zinc-800 dark:text-zinc-200">
                          {money(qd.price)}
                        </p>
                        <p
                          className={cn(
                            "font-mono text-xs",
                            up
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-red-600 dark:text-red-400"
                          )}
                        >
                          {signedPct(qd.change_pct, 1)}
                        </p>
                      </>
                    ) : (
                      <span className="font-mono text-sm text-zinc-400 dark:text-zinc-600">—</span>
                    )}
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </Card>

      {!loading && rows.length === 0 && (
        <p className="text-center text-sm text-zinc-400 dark:text-zinc-600 py-8">
          No matches{query ? ` for “${query}”` : ""}.
        </p>
      )}
    </div>
  );
}
