"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FomcRateProbability } from "@/lib/types";

function fmtRate(low: number, high: number): string {
  if (low === high) return `${low.toFixed(2)}%`;
  return `${low.toFixed(2)}–${high.toFixed(2)}%`;
}

export function FedWatchCard() {
  const { data: probabilities, isLoading } = useQuery<FomcRateProbability[]>({
    queryKey: ["fomcRateProbabilities"],
    queryFn: () => fomcApi.rateProbabilities(),
    staleTime: 30 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <Card className="p-5">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2 mb-3">
          <BarChart3 size={15} className="text-sky-600 dark:text-sky-400" />
          Rate Expectations
        </h3>
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-8 rounded bg-zinc-100 dark:bg-zinc-800/60 animate-pulse" />
          ))}
        </div>
      </Card>
    );
  }

  if (!probabilities || probabilities.length === 0) {
    return null;
  }

  const maxProb = Math.max(...probabilities.map((p) => p.probability));

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
          <BarChart3 size={15} className="text-sky-600 dark:text-sky-400" />
          Rate Expectations — Next Meeting
        </h3>
        <span className="text-[11px] text-zinc-500">CME FedWatch</span>
      </div>
      <p className="text-[11px] text-zinc-500 mb-4">
        Market-implied probabilities for each target rate outcome
      </p>

      <div className="space-y-2.5">
        {probabilities.map((p, i) => {
          const isTop = p.probability === maxProb;
          return (
            <div key={i} className="flex items-center gap-3">
              <span className={cn(
                "text-xs font-mono w-28 shrink-0 text-right",
                isTop ? "text-sky-600 dark:text-sky-400 font-semibold" : "text-zinc-500 dark:text-zinc-400",
              )}>
                {fmtRate(p.target_rate_low, p.target_rate_high)}
              </span>
              <div className="flex-1 h-6 bg-zinc-100 dark:bg-zinc-800 rounded relative overflow-hidden">
                <div
                  className={cn(
                    "absolute inset-y-0 left-0 rounded transition-all",
                    isTop ? "bg-sky-500/60" : "bg-zinc-300 dark:bg-zinc-600/60",
                  )}
                  style={{ width: `${Math.max(2, p.probability)}%` }}
                />
              </div>
              <span className={cn(
                "text-[11px] font-mono font-semibold w-12 shrink-0",
                isTop ? "text-sky-600 dark:text-sky-400" : "text-zinc-500 dark:text-zinc-400",
              )}>
                {p.probability.toFixed(1)}%
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
