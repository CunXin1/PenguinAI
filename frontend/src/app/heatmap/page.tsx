"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { LayoutGrid, Loader2 } from "lucide-react";
import { marketData } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Heatmap, tileGradient } from "@/components/market/Heatmap";
import { cn, money, signedPct } from "@/lib/utils";
import type { HeatmapPeriod, HeatmapResponse } from "@/lib/types";

const SIZES = [30, 50, 100, 200] as const;
const PERIODS: HeatmapPeriod[] = ["1D", "1W", "1M", "3M", "1Y"];
// % that maps to full tile color, per period (a 1Y move is far bigger than a 1D one).
const SCALE: Record<HeatmapPeriod, number> = { "1D": 3, "1W": 6, "1M": 12, "3M": 25, "1Y": 50 };
const REFRESH_MS = 15_000;
const H = 640;
// Static legend ramp (matches the tile color stops): red ← neutral → green.
const LEGEND =
  "linear-gradient(to right, rgb(244,63,94), rgb(190,30,35), rgb(60,62,68), rgb(21,128,61), rgb(34,197,94))";

export default function HeatmapPage() {
  const [limit, setLimit] = useState<number>(50);
  const [period, setPeriod] = useState<HeatmapPeriod>("1D");

  const { data, isLoading, isError } = useQuery<HeatmapResponse>({
    queryKey: ["heatmap", limit, period],
    queryFn: () => marketData.heatmap(limit, period),
    // Poll on 1D regardless of the badge — lets the backend observe live ticks
    // advancing and flip Closed→Live (and keeps prices fresh). Other periods are
    // historical and don't move, so no polling.
    refetchInterval: period === "1D" ? REFRESH_MS : false,
  });

  const open = data?.market_open ?? false;
  const items = data?.items ?? [];
  const indices = data?.indices ?? [];
  const asOf = data?.as_of ? new Date(data.as_of) : null;
  const scale = SCALE[period];

  const upN = items.filter((i) => i.change_pct > 0).length;
  const downN = items.filter((i) => i.change_pct < 0).length;
  const avg = items.length ? items.reduce((s, i) => s + i.change_pct, 0) / items.length : 0;

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-4">
      {/* Header: title + status · period toggle */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2.5">
          <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
            <LayoutGrid size={20} className="text-sky-500 dark:text-sky-400" /> Market Map
          </h1>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1",
              open
                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
                : "bg-zinc-500/10 text-zinc-500 dark:text-zinc-400 ring-zinc-500/20"
            )}
          >
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full",
                open ? "bg-emerald-500 animate-pulse" : "bg-zinc-400 dark:bg-zinc-500"
              )}
            />
            {open ? "Live" : "Closed"}
          </span>
        </div>

        {/* Period toggle */}
        <div className="flex gap-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-800/60 p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "px-3 py-1 rounded-md text-xs font-semibold transition-colors",
                period === p
                  ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm"
                  : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Index tiles */}
      {indices.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {indices.map((ix) => {
            const up = ix.change_pct >= 0;
            return (
              <Link
                key={ix.ticker}
                href={`/signals/${ix.ticker}`}
                className="rounded-xl p-3 ring-1 ring-inset ring-white/10 transition-transform hover:scale-[1.02] hover:ring-white/30"
                style={{ background: tileGradient(ix.change_pct, scale) }}
                title={`${ix.label} (${ix.ticker})`}
              >
                <div className="text-[11px] font-medium text-white/80">{ix.label}</div>
                <div className="flex items-baseline justify-between mt-0.5">
                  <span className="font-mono font-bold text-white">{ix.ticker}</span>
                  <span className="font-mono text-sm font-semibold text-white">
                    {signedPct(ix.change_pct)}
                  </span>
                </div>
                <div className="text-[11px] font-mono text-white/70 mt-0.5">{money(ix.price)}</div>
              </Link>
            );
          })}
        </div>
      )}

      {/* Sub-row: breadth · size selector */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        {items.length > 0 ? (
          <div className="flex items-center gap-2.5 text-sm">
            <span className="text-zinc-500 dark:text-zinc-400">Top {items.length} by market cap</span>
            <span className="text-zinc-300 dark:text-zinc-700">·</span>
            <span className="text-emerald-600 dark:text-emerald-400 font-medium tabular-nums">
              ▲ {upN}
            </span>
            <span className="text-red-600 dark:text-red-400 font-medium tabular-nums">
              ▼ {downN}
            </span>
            <span className="text-zinc-300 dark:text-zinc-700">·</span>
            <span
              className={cn(
                "font-mono font-medium",
                avg >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-red-600 dark:text-red-400"
              )}
            >
              avg {signedPct(avg)}
            </span>
          </div>
        ) : (
          <span />
        )}

        <div className="flex gap-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-800/60 p-0.5">
          {SIZES.map((n) => (
            <button
              key={n}
              onClick={() => setLimit(n)}
              className={cn(
                "px-2.5 py-1 rounded-md text-xs font-semibold transition-colors",
                limit === n
                  ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm"
                  : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              )}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* Map */}
      <Card className="p-2 sm:p-2.5 bg-zinc-100/80 dark:bg-zinc-950/60">
        {isLoading ? (
          <div
            className="grid place-items-center text-sm text-zinc-400 dark:text-zinc-600"
            style={{ height: H }}
          >
            <span className="flex items-center gap-2">
              <Loader2 size={16} className="animate-spin text-sky-500" /> Loading market…
            </span>
          </div>
        ) : isError ? (
          <div
            className="grid place-items-center text-sm text-zinc-400 dark:text-zinc-600"
            style={{ height: H }}
          >
            Couldn&apos;t load market data.
          </div>
        ) : items.length === 0 ? (
          <div
            className="grid place-items-center text-sm text-zinc-400 dark:text-zinc-600 text-center px-6"
            style={{ height: H }}
          >
            No market-cap data yet — run the market-cap backfill to populate the map.
          </div>
        ) : (
          <Heatmap tiles={items} height={H} scale={scale} />
        )}
      </Card>

      {/* Footer: legend + as-of */}
      <div className="flex items-center justify-between flex-wrap gap-3 text-xs text-zinc-400 dark:text-zinc-600">
        <div className="flex items-center gap-2">
          <span className="font-mono">−{scale}%</span>
          <span
            className="h-2.5 w-44 rounded-full ring-1 ring-black/10 dark:ring-white/10"
            style={{ background: LEGEND }}
          />
          <span className="font-mono">+{scale}%</span>
        </div>
        <span>
          {period} change · sized by market cap ·{" "}
          {asOf
            ? `as of ${asOf.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}`
            : "—"}
        </span>
      </div>
    </div>
  );
}
