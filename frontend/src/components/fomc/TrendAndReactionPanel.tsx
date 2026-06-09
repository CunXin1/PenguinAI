"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, TrendingDown } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FomcTrendPoint, FomcMarketReaction } from "@/lib/types";

const COUNT_OPTIONS = [10, 20, 30] as const;

function scoreLabel(score: number): string {
  if (score >= 0.3) return "Hawkish";
  if (score >= 0.1) return "Slightly Hawkish";
  if (score > -0.1) return "Neutral";
  if (score > -0.3) return "Slightly Dovish";
  return "Dovish";
}

function scoreColor(score: number): string {
  if (score >= 0.3) return "text-red-600 dark:text-red-400";
  if (score >= 0.1) return "text-orange-600 dark:text-orange-400";
  if (score > -0.1) return "text-zinc-600 dark:text-zinc-400";
  if (score > -0.3) return "text-sky-600 dark:text-sky-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr + "T12:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" });
  } catch {
    return dateStr;
  }
}

function fmtRate(low: number, high: number): string {
  if (low === high) return `${low.toFixed(2)}%`;
  return `${low.toFixed(2)}–${high.toFixed(2)}%`;
}

function CountSelector({
  value,
  onChange,
}: {
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="flex gap-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-800/60 p-0.5 w-fit">
      {COUNT_OPTIONS.map((n) => (
        <button
          key={n}
          onClick={() => onChange(n)}
          className={cn(
            "px-2.5 py-1 rounded-md text-xs font-semibold transition-colors",
            value === n
              ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm"
              : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
          )}
        >
          {n}
        </button>
      ))}
    </div>
  );
}

function TrendChart({ points }: { points: FomcTrendPoint[] }) {
  if (points.length === 0) {
    return <p className="text-sm text-zinc-500 text-center py-4">No trend data available.</p>;
  }
  const maxAbs = Math.max(0.5, ...points.map((p) => Math.abs(p.score)));

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[10px] text-zinc-400 dark:text-zinc-500 px-1">
        <span>Dovish</span>
        <span>Neutral</span>
        <span>Hawkish</span>
      </div>
      {points.map((p) => {
        const isHawk = p.score >= 0;
        return (
          <div key={p.date} className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-zinc-500 w-20 shrink-0 text-right">
              {formatDate(p.date)}
            </span>
            <div className="flex-1 h-5 relative">
              <div className="absolute inset-0 bg-zinc-100 dark:bg-zinc-800 rounded" />
              <div className="absolute top-0 bottom-0 left-1/2 w-px bg-zinc-300 dark:bg-zinc-600" />
              <div
                className={cn(
                  "absolute top-0.5 bottom-0.5 rounded",
                  isHawk ? "bg-red-500/70" : "bg-emerald-500/70",
                )}
                style={
                  isHawk
                    ? { left: "50%", width: `${(p.score / maxAbs) * 50}%` }
                    : { right: "50%", width: `${(-p.score / maxAbs) * 50}%` }
                }
              />
            </div>
            <span className={cn("text-[10px] font-mono w-12 shrink-0", scoreColor(p.score))}>
              {p.score >= 0 ? "+" : ""}{p.score.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function MarketReactionTable({ reactions }: { reactions: FomcMarketReaction[] }) {
  if (reactions.length === 0) {
    return <p className="text-sm text-zinc-500 text-center py-4">No market reaction data.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-200 dark:border-zinc-800">
            <th className="text-left py-1 font-medium text-zinc-500">Date</th>
            <th className="text-right py-1 font-medium text-zinc-500">Rate</th>
            <th className="text-right py-1 font-medium text-zinc-500">SPY</th>
            <th className="text-right py-1 font-medium text-zinc-500">Return</th>
          </tr>
        </thead>
        <tbody>
          {reactions.map((r) => {
            const ret = r.spy_return_pct;
            const isPos = ret !== null && ret >= 0;
            return (
              <tr key={r.date} className="border-b border-zinc-100 dark:border-zinc-800/50">
                <td className="py-1 font-mono text-zinc-700 dark:text-zinc-300">{formatDate(r.date)}</td>
                <td className="py-1 text-right font-mono text-zinc-500">
                  {r.rate_low != null && r.rate_high != null ? fmtRate(r.rate_low, r.rate_high) : "—"}
                </td>
                <td className="py-1 text-right font-mono text-zinc-500">
                  {r.spy_close != null ? `$${r.spy_close.toFixed(2)}` : "—"}
                </td>
                <td className={cn(
                  "py-1 text-right font-mono font-semibold",
                  ret === null ? "text-zinc-400" : isPos ? "text-emerald-500" : "text-red-500",
                )}>
                  {ret !== null ? `${isPos ? "+" : ""}${ret.toFixed(2)}%` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function TrendAndReactionRow() {
  const [count, setCount] = useState<number>(10);

  const { data: trend } = useQuery<FomcTrendPoint[]>({
    queryKey: ["fomcTrend", count],
    queryFn: () => fomcApi.trend(count),
    staleTime: 60 * 60 * 1000,
  });

  const { data: rawReactions } = useQuery<FomcMarketReaction[]>({
    queryKey: ["fomcMarketReaction", count],
    queryFn: () => fomcApi.marketReaction(count),
    staleTime: 60 * 60 * 1000,
  });

  // Backend returns newest first — reverse to chronological (oldest first)
  const reactions = rawReactions ? [...rawReactions].reverse() : [];

  const latestScore = trend && trend.length > 0 ? trend[trend.length - 1] : null;

  return (
    <div className="space-y-3">
      {/* Shared count selector */}
      <div className="flex items-center justify-between">
        <CountSelector value={count} onChange={setCount} />
        {latestScore && (
          <span className={cn("flex items-center gap-1 text-xs font-semibold", scoreColor(latestScore.score))}>
            {latestScore.score >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {scoreLabel(latestScore.score)}
          </span>
        )}
      </div>

      {/* Two panels side by side */}
      <div className="grid lg:grid-cols-2 gap-5">
        <Card className="p-5">
          <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
            Hawk/Dove Score
          </h3>
          <p className="text-[11px] text-zinc-500 mb-3">Positive = hawkish · Negative = dovish</p>
          <TrendChart points={trend ?? []} />
        </Card>

        <Card className="p-5">
          <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
            SPY Market Reaction
          </h3>
          <p className="text-[11px] text-zinc-500 mb-3">Close-to-close return on FOMC day</p>
          <MarketReactionTable reactions={reactions} />
        </Card>
      </div>
    </div>
  );
}
