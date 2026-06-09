"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Crown, Search, TrendingUp, TrendingDown, Users, X } from "lucide-react";
import { celebrityHoldings as api } from "@/lib/api";
import { getCelebrityMeta, getCelebrityColor } from "@/lib/celebrities";
import { CelebrityRing } from "@/components/celebrity/CelebrityRing";
import { Card } from "@/components/ui/Card";
import { StatTile } from "@/components/ui/StatTile";
import { cn, compact, timeAgo } from "@/lib/utils";
import type {
  CelebrityHolding,
  CelebritySummary,
  CelebAction,
} from "@/lib/types";

type ActionFilter = "ALL" | "BUY" | "SELL";

const ACTION_FILTERS: { key: ActionFilter; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "BUY", label: "Buys" },
  { key: "SELL", label: "Sells" },
];

interface TickerGroup {
  ticker: string;
  ticker_name: string;
  buyers: { celebrity: string; value_usd: number | null }[];
  sellers: { celebrity: string; value_usd: number | null }[];
  latest_date: string;
}

function groupByTicker(holdings: CelebrityHolding[]): TickerGroup[] {
  const map = new Map<string, TickerGroup>();
  for (const h of holdings) {
    if (h.action === "HOLD") continue;
    let g = map.get(h.ticker);
    if (!g) {
      g = {
        ticker: h.ticker,
        ticker_name: h.ticker_name,
        buyers: [],
        sellers: [],
        latest_date: h.reported_at,
      };
      map.set(h.ticker, g);
    }
    if (h.reported_at > g.latest_date) g.latest_date = h.reported_at;
    const list = h.action === "BUY" ? g.buyers : g.sellers;
    if (!list.some((x) => x.celebrity === h.celebrity)) {
      list.push({ celebrity: h.celebrity, value_usd: h.value_usd });
    }
  }
  return Array.from(map.values()).sort((a, b) =>
    b.latest_date.localeCompare(a.latest_date)
  );
}

export default function CelebrityHoldingsPage() {
  const [selectedCeleb, setSelectedCeleb] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState<ActionFilter>("ALL");
  const [q, setQ] = useState("");
  const [popover, setPopover] = useState<{
    celebrity: string;
    action: "BUY" | "SELL" | "HOLD";
  } | null>(null);

  const { data: stats } = useQuery<CelebritySummary[]>({
    queryKey: ["celebStats"],
    queryFn: () => api.stats(),
  });

  const { data: holdings } = useQuery<CelebrityHolding[]>({
    queryKey: ["celebHoldings"],
    queryFn: () => api.list(500),
  });

  const allStats = useMemo(() => stats ?? [], [stats]);
  const allHoldings = useMemo(() => holdings ?? [], [holdings]);

  const totals = useMemo(() => {
    const buys = allHoldings.filter((h) => h.action === "BUY").length;
    const sells = allHoldings.filter((h) => h.action === "SELL").length;
    return { tracked: allStats.length, buys, sells };
  }, [allStats, allHoldings]);

  const tickerGroups = useMemo(() => {
    const groups = groupByTicker(allHoldings);
    const needle = q.trim().toUpperCase();
    return groups.filter((g) => {
      if (selectedCeleb) {
        const hasCeleb =
          g.buyers.some((b) => b.celebrity === selectedCeleb) ||
          g.sellers.some((s) => s.celebrity === selectedCeleb);
        if (!hasCeleb) return false;
      }
      if (actionFilter === "BUY" && g.buyers.length === 0) return false;
      if (actionFilter === "SELL" && g.sellers.length === 0) return false;
      if (
        needle &&
        !g.ticker.includes(needle) &&
        !g.ticker_name.toUpperCase().includes(needle)
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
          <Crown size={20} className="text-amber-500 dark:text-amber-400" />{" "}
          Celebrity Holdings
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          Track what Buffett, Pelosi, Cathie Wood and other institutional
          investors are buying and selling
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

      {/* Celebrity ring avatars */}
      <div className="flex gap-6 overflow-x-auto pb-2 -mx-4 px-4 scrollbar-none">
        {allStats.map((s) => {
          const meta = getCelebrityMeta(s.celebrity);
          const color = getCelebrityColor(s.celebrity);
          const isSelected = selectedCeleb === s.celebrity;
          return (
            <div
              key={s.celebrity}
              className="shrink-0 flex flex-col items-center gap-2"
            >
              <CelebrityRing
                buys={s.buys}
                sells={s.sells}
                holds={s.total_trades - s.buys - s.sells}
                size={120}
                initials={meta.avatar}
                gradientClass={color}
                image={meta.image}
                selected={isSelected}
                onCenterClick={() =>
                  setSelectedCeleb(isSelected ? null : s.celebrity)
                }
                onSegmentClick={(action) =>
                  setPopover(
                    popover?.celebrity === s.celebrity &&
                      popover.action === action
                      ? null
                      : { celebrity: s.celebrity, action }
                  )
                }
              />
              <Link
                href={`/celebrity-holdings/${s.celebrity}`}
                className="text-xs text-zinc-400 hover:text-white transition-colors text-center leading-tight"
              >
                {meta.name}
              </Link>
            </div>
          );
        })}
      </div>

      {/* Segment detail panel */}
      {popover && (
        <SegmentDetail
          celebrity={popover.celebrity}
          action={popover.action}
          holdings={allHoldings}
          onClose={() => setPopover(null)}
        />
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 items-center">
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

      {/* Ticker tracker */}
      <Card className="overflow-hidden divide-y divide-zinc-200 dark:divide-zinc-800/70">
        <div className="grid grid-cols-12 gap-2 items-center px-4 py-2 text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-wider font-medium">
          <div className="col-span-3">Ticker</div>
          <div className="col-span-4">Buyers</div>
          <div className="col-span-3">Sellers</div>
          <div className="col-span-2 text-right">Date</div>
        </div>
        {tickerGroups.map((g) => (
          <TickerRow key={g.ticker} group={g} />
        ))}
      </Card>

      {tickerGroups.length === 0 && (
        <p className="text-center text-sm text-zinc-400 dark:text-zinc-600 py-12">
          No tickers match your filters{q ? ` for "${q}"` : ""}.
        </p>
      )}

      <p className="text-xs text-zinc-400 dark:text-zinc-600 text-center pt-2">
        Data from SEC EDGAR 13F/13D filings, Quiver Quant congressional trades,
        and ARK Invest daily disclosures.
      </p>
    </div>
  );
}

/* ── Segment detail panel (shown below avatars on ring click) ─────────────── */

function SegmentDetail({
  celebrity,
  action,
  holdings,
  onClose,
}: {
  celebrity: string;
  action: "BUY" | "SELL" | "HOLD";
  holdings: CelebrityHolding[];
  onClose: () => void;
}) {
  const meta = getCelebrityMeta(celebrity);
  const tickers = useMemo(() => {
    const seen = new Set<string>();
    return holdings
      .filter((h) => h.celebrity === celebrity && h.action === action)
      .filter((h) => {
        if (seen.has(h.ticker)) return false;
        seen.add(h.ticker);
        return true;
      });
  }, [celebrity, action, holdings]);

  const label =
    action === "BUY" ? "Buying" : action === "SELL" ? "Selling" : "Holding";

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-200">
          {meta.name} —{" "}
          <span
            className={
              action === "BUY"
                ? "text-emerald-400"
                : action === "SELL"
                  ? "text-red-400"
                  : "text-zinc-400"
            }
          >
            {label}
          </span>
          <span className="text-zinc-500 font-normal ml-2">
            {tickers.length} tickers
          </span>
        </p>
        <button
          onClick={onClose}
          className="text-zinc-500 hover:text-white transition-colors"
        >
          <X size={16} />
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {tickers.map((t) => (
          <Link
            key={t.ticker}
            href={`/signals/${t.ticker}`}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-mono font-semibold transition-colors",
              action === "BUY"
                ? "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
                : action === "SELL"
                  ? "bg-red-500/10 text-red-400 hover:bg-red-500/20"
                  : "bg-zinc-500/10 text-zinc-400 hover:bg-zinc-500/20"
            )}
          >
            {t.ticker}
            <span className="text-[10px] text-zinc-500 ml-1.5 font-sans font-normal">
              {t.ticker_name}
            </span>
          </Link>
        ))}
        {tickers.length === 0 && (
          <p className="text-xs text-zinc-500">No tickers</p>
        )}
      </div>
    </Card>
  );
}

/* ── Celebrity pill shown in tracker rows ─────────────────────────────────── */

function CelebPill({
  celebrity,
  action,
}: {
  celebrity: string;
  action: "BUY" | "SELL";
}) {
  const meta = getCelebrityMeta(celebrity);
  const color = getCelebrityColor(celebrity);
  const isBuy = action === "BUY";
  return (
    <Link
      href={`/celebrity-holdings/${celebrity}`}
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-[11px] font-medium transition-colors",
        isBuy
          ? "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
          : "bg-red-500/10 text-red-400 hover:bg-red-500/20"
      )}
    >
      <span
        className={cn(
          "w-4 h-4 rounded-full bg-gradient-to-br grid place-items-center text-[7px] font-bold text-white shrink-0",
          color
        )}
      >
        {meta.avatar.charAt(0)}
      </span>
      {meta.name.split(" ").pop()}
    </Link>
  );
}

/* ── One row in the ticker tracker table ──────────────────────────────────── */

function TickerRow({ group: g }: { group: TickerGroup }) {
  return (
    <div className="grid grid-cols-12 gap-2 items-center px-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/20 transition-colors">
      {/* Ticker */}
      <div className="col-span-3 min-w-0">
        <Link href={`/signals/${g.ticker}`} className="group">
          <span className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100 group-hover:text-sky-400 transition-colors">
            {g.ticker}
          </span>
          <p className="text-xs text-zinc-500 truncate mt-0.5">
            {g.ticker_name}
          </p>
        </Link>
      </div>

      {/* Buyers */}
      <div className="col-span-4 flex flex-wrap gap-1">
        {g.buyers.map((b) => (
          <CelebPill key={b.celebrity} celebrity={b.celebrity} action="BUY" />
        ))}
        {g.buyers.length === 0 && (
          <span className="text-xs text-zinc-600">—</span>
        )}
      </div>

      {/* Sellers */}
      <div className="col-span-3 flex flex-wrap gap-1">
        {g.sellers.map((s) => (
          <CelebPill key={s.celebrity} celebrity={s.celebrity} action="SELL" />
        ))}
        {g.sellers.length === 0 && (
          <span className="text-xs text-zinc-600">—</span>
        )}
      </div>

      {/* Date */}
      <div className="col-span-2 text-right">
        <p className="text-xs text-zinc-500">{timeAgo(g.latest_date)}</p>
      </div>
    </div>
  );
}
