"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Crown, Search, TrendingUp, TrendingDown, Users } from "lucide-react";
import { celebrityHoldings as api } from "@/lib/api";
import { MOCK_CELEB_HOLDINGS, MOCK_CELEB_STATS } from "@/lib/mock";
import { getCelebrityMeta, getCelebrityColor } from "@/lib/celebrities";
import { Card } from "@/components/ui/Card";
import { StatTile } from "@/components/ui/StatTile";
import { cn, compact, timeAgo } from "@/lib/utils";
import type { CelebrityHolding, CelebritySummary, CelebAction } from "@/lib/types";

type ActionFilter = "ALL" | CelebAction;

const ACTION_FILTERS: { key: ActionFilter; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "BUY", label: "Buy" },
  { key: "SELL", label: "Sell" },
  { key: "HOLD", label: "Hold" },
];

const ACTION_STYLE: Record<CelebAction, string> = {
  BUY: "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  SELL: "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30",
  HOLD: "text-zinc-600 dark:text-zinc-400 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50",
};

export default function CelebrityHoldingsPage() {
  const [selectedCeleb, setSelectedCeleb] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState<ActionFilter>("ALL");
  const [q, setQ] = useState("");

  const { data: stats } = useQuery<CelebritySummary[]>({
    queryKey: ["celebStats"],
    queryFn: async () => {
      try {
        const s = await api.stats();
        return Array.isArray(s) && s.length ? s : MOCK_CELEB_STATS;
      } catch {
        return MOCK_CELEB_STATS;
      }
    },
    initialData: MOCK_CELEB_STATS,
  });

  const { data: holdings } = useQuery<CelebrityHolding[]>({
    queryKey: ["celebHoldings"],
    queryFn: async () => {
      try {
        const h = await api.list(300);
        return Array.isArray(h) && h.length ? h : MOCK_CELEB_HOLDINGS;
      } catch {
        return MOCK_CELEB_HOLDINGS;
      }
    },
    initialData: MOCK_CELEB_HOLDINGS,
  });

  const allStats = stats ?? MOCK_CELEB_STATS;
  const allHoldings = holdings ?? MOCK_CELEB_HOLDINGS;

  const totals = useMemo(() => {
    const buys = allHoldings.filter((h) => h.action === "BUY").length;
    const sells = allHoldings.filter((h) => h.action === "SELL").length;
    return { tracked: allStats.length, buys, sells };
  }, [allStats, allHoldings]);

  const filtered = useMemo(() => {
    const needle = q.trim().toUpperCase();
    return allHoldings.filter((h) => {
      if (selectedCeleb && h.celebrity !== selectedCeleb) return false;
      if (actionFilter !== "ALL" && h.action !== actionFilter) return false;
      if (
        needle &&
        !h.ticker.includes(needle) &&
        !h.ticker_name.toUpperCase().includes(needle) &&
        !getCelebrityMeta(h.celebrity).name.toUpperCase().includes(needle)
      )
        return false;
      return true;
    });
  }, [allHoldings, selectedCeleb, actionFilter, q]);

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <Crown size={20} className="text-amber-500 dark:text-amber-400" /> Smart Money
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          Track what Buffett, Pelosi, Cathie Wood and other institutional investors are buying and
          selling
        </p>
      </div>

      {/* Stat tiles */}
      <div className="grid grid-cols-3 gap-3">
        <StatTile
          label="Tracked"
          value={totals.tracked}
          accent="brand"
          sub="celebrities"
          icon={<Users size={16} />}
        />
        <StatTile
          label="Buys"
          value={totals.buys}
          accent="up"
          sub="recent transactions"
          icon={<TrendingUp size={16} />}
        />
        <StatTile
          label="Sells"
          value={totals.sells}
          accent="down"
          sub="recent transactions"
          icon={<TrendingDown size={16} />}
        />
      </div>

      {/* Celebrity cards */}
      <div className="flex gap-3 overflow-x-auto pb-1 -mx-4 px-4 scrollbar-none">
        {allStats.slice(0, 8).map((s) => {
          const meta = getCelebrityMeta(s.celebrity);
          const color = getCelebrityColor(s.celebrity);
          const isSelected = selectedCeleb === s.celebrity;
          return (
            <button
              key={s.celebrity}
              type="button"
              onClick={() => setSelectedCeleb(isSelected ? null : s.celebrity)}
              className={cn(
                "shrink-0 rounded-xl border p-3 min-w-[160px] text-left transition-all",
                isSelected
                  ? "border-sky-500 bg-sky-500/5 dark:bg-sky-500/10 ring-1 ring-sky-500/40"
                  : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 hover:border-zinc-300 dark:hover:border-zinc-700"
              )}
            >
              <div className="flex items-center gap-2 mb-2">
                <div
                  className={cn(
                    "w-8 h-8 rounded-full bg-gradient-to-br grid place-items-center text-xs font-bold text-white shrink-0",
                    color
                  )}
                >
                  {meta.avatar}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-zinc-900 dark:text-white truncate">
                    {meta.name}
                  </p>
                  <p className="text-[10px] text-zinc-500 truncate">{meta.title}</p>
                </div>
              </div>
              <div className="flex items-center gap-3 text-xs">
                <span className="text-emerald-600 dark:text-emerald-400 font-medium">
                  {s.buys} buys
                </span>
                <span className="text-red-500 dark:text-red-400 font-medium">{s.sells} sells</span>
              </div>
              <p className="text-[10px] text-zinc-400 dark:text-zinc-600 mt-1">
                Latest: {timeAgo(s.latest_trade)}
              </p>
            </button>
          );
        })}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1">
          {ACTION_FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setActionFilter(f.key)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                actionFilter === f.key
                  ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                  : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
              )}
            >
              {f.label}
            </button>
          ))}
          {selectedCeleb && (
            <button
              onClick={() => setSelectedCeleb(null)}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-sky-600 dark:text-sky-400 bg-sky-500/10 border border-sky-500/30 transition-colors hover:bg-sky-500/20"
            >
              {getCelebrityMeta(selectedCeleb).name} &times;
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 w-56 focus-within:border-sky-500/60 transition-colors">
          <Search size={14} className="text-zinc-500 shrink-0" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter ticker or name..."
            className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-full"
          />
        </div>
      </div>

      {/* Transaction table */}
      <Card className="overflow-hidden divide-y divide-zinc-200 dark:divide-zinc-800/70">
        {/* Header row */}
        <div className="grid grid-cols-12 gap-2 items-center px-4 py-2 text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-wider font-medium">
          <div className="col-span-3 sm:col-span-3">Ticker</div>
          <div className="col-span-3 sm:col-span-2">Celebrity</div>
          <div className="col-span-2 sm:col-span-1 text-center">Action</div>
          <div className="hidden sm:block col-span-2 text-right">Shares</div>
          <div className="hidden sm:block col-span-2 text-right">Value</div>
          <div className="col-span-4 sm:col-span-2 text-right">Date</div>
        </div>
        {filtered.map((h) => (
          <HoldingRow key={h.id} h={h} />
        ))}
      </Card>

      {filtered.length === 0 && (
        <p className="text-center text-sm text-zinc-400 dark:text-zinc-600 py-12">
          No transactions match your filters{q ? ` for "${q}"` : ""}.
        </p>
      )}

      <p className="text-xs text-zinc-400 dark:text-zinc-600 text-center pt-2">
        Data from SEC EDGAR 13F filings, House/Senate Stock Watcher, and ARK Invest daily
        disclosures.
      </p>
    </div>
  );
}

function HoldingRow({ h }: { h: CelebrityHolding }) {
  const meta = getCelebrityMeta(h.celebrity);
  const color = getCelebrityColor(h.celebrity);

  return (
    <Link
      href={`/signals/${h.ticker}`}
      className="grid grid-cols-12 gap-2 items-center px-4 py-3 hover:bg-zinc-100 dark:hover:bg-zinc-800/30 transition-colors"
    >
      {/* Ticker + name */}
      <div className="col-span-3 sm:col-span-3 min-w-0">
        <span className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100">
          {h.ticker}
        </span>
        <p className="text-xs text-zinc-500 truncate mt-0.5">{h.ticker_name}</p>
      </div>

      {/* Celebrity */}
      <div className="col-span-3 sm:col-span-2 flex items-center gap-1.5 min-w-0">
        <div
          className={cn(
            "w-5 h-5 rounded-full bg-gradient-to-br grid place-items-center text-[8px] font-bold text-white shrink-0",
            color
          )}
        >
          {meta.avatar}
        </div>
        <span className="text-xs text-zinc-700 dark:text-zinc-300 truncate">{meta.name}</span>
      </div>

      {/* Action badge */}
      <div className="col-span-2 sm:col-span-1 flex justify-center">
        <span
          className={cn(
            "px-2 py-0.5 rounded-md text-[10px] font-semibold border leading-none",
            ACTION_STYLE[h.action]
          )}
        >
          {h.action}
        </span>
      </div>

      {/* Shares */}
      <div className="hidden sm:block col-span-2 text-right">
        <p className="font-mono text-sm text-zinc-700 dark:text-zinc-300">
          {h.shares != null ? compact(h.shares) : "—"}
        </p>
      </div>

      {/* Value */}
      <div className="hidden sm:block col-span-2 text-right">
        <p className="font-mono text-sm text-zinc-700 dark:text-zinc-300">
          {h.value_usd != null ? `$${compact(h.value_usd)}` : "—"}
        </p>
      </div>

      {/* Date */}
      <div className="col-span-4 sm:col-span-2 text-right">
        <p className="text-xs text-zinc-500">{timeAgo(h.reported_at)}</p>
        <p className="text-[10px] text-zinc-400 dark:text-zinc-600">
          {h.source_type === "13F" ? "13F Filing" : "Disclosure"}
        </p>
      </div>
    </Link>
  );
}
