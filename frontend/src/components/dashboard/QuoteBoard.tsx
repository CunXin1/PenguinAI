"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { LayoutGrid, TrendingUp, TrendingDown } from "lucide-react";
import { marketData } from "@/lib/api";
import { TOP30, mockQuotes } from "@/lib/mock";
import { Card } from "@/components/ui/Card";
import { money, signedPct } from "@/lib/utils";
import type { Quote } from "@/lib/types";

const REFRESH_MS = 30_000; // ~per-minute 1-min bars; poll twice a minute to catch the forming bar

interface BoardData {
  quotes: Quote[];
  live: boolean;
}

export function QuoteBoard() {
  const { data } = useQuery<BoardData>({
    queryKey: ["quoteBoard", "top30"],
    queryFn: async () => {
      try {
        const res = await marketData.quotes(TOP30);
        const live = res?.quotes ?? [];
        if (live.length === 0) return { quotes: mockQuotes(TOP30), live: false };
        // Keep TOP30 order; fill any symbol the stream hasn't populated yet from demo data.
        const map = new Map(live.map((q) => [q.ticker, q]));
        const merged = TOP30.map((t) => map.get(t) ?? mockQuotes([t])[0]);
        return { quotes: merged, live: true };
      } catch {
        return { quotes: mockQuotes(TOP30), live: false };
      }
    },
    initialData: { quotes: mockQuotes(TOP30), live: false },
    refetchInterval: REFRESH_MS,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });

  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
          <LayoutGrid size={15} className="text-sky-500 dark:text-sky-400" />
          Live Quotes · Top 30
        </h2>
        <span className="flex items-center gap-1.5 text-[11px] font-medium">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              data.live ? "bg-emerald-500 animate-pulse" : "bg-zinc-400 dark:bg-zinc-600"
            }`}
          />
          <span className={data.live ? "text-emerald-600 dark:text-emerald-400" : "text-zinc-400 dark:text-zinc-600"}>
            {data.live ? "Live · 30s" : "Demo"}
          </span>
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
        {data.quotes.map((q) => {
          const up = q.change_pct >= 0;
          return (
            <Link
              key={q.ticker}
              href={`/signals/${q.ticker}`}
              className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 px-3 py-2 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors"
            >
              <div className="flex items-center justify-between gap-1">
                <span className="font-mono font-bold text-sm text-zinc-900 dark:text-white truncate">{q.ticker}</span>
                {up ? (
                  <TrendingUp size={12} className="text-emerald-600 dark:text-emerald-400 shrink-0" />
                ) : (
                  <TrendingDown size={12} className="text-red-600 dark:text-red-400 shrink-0" />
                )}
              </div>
              <div className="font-mono text-sm text-zinc-800 dark:text-zinc-200 mt-0.5">{money(q.price)}</div>
              <div className={`font-mono text-xs mt-0.5 ${up ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                {signedPct(q.change_pct, 2)}
              </div>
            </Link>
          );
        })}
      </div>
    </Card>
  );
}
