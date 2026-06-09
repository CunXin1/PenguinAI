"use client";

import Link from "next/link";
import { Star, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { Sparkline } from "@/components/ui/Sparkline";
import { useWatchlist } from "@/hooks/useWatchlist";
import { useMiniQuotes } from "@/hooks/useMiniQuotes";
import { cn, signedPct } from "@/lib/utils";

const MAX_ROWS = 6;

export function WatchlistWidget() {
  const { tickers, signalByTicker, ready } = useWatchlist();
  const shown = tickers.slice(0, MAX_ROWS);
  const { data: quotes } = useMiniQuotes(shown);

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
          <Star size={15} className="text-amber-500 dark:text-amber-400" />
          My Watchlist
        </h3>
        <Link
          href="/watchlist"
          className="text-xs text-zinc-500 hover:text-sky-600 dark:hover:text-sky-400 flex items-center gap-1 transition-colors"
        >
          Manage <ArrowRight size={12} />
        </Link>
      </div>

      {!ready ? (
        <div className="space-y-1.5">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-8 rounded-lg bg-zinc-100 dark:bg-zinc-800/40 animate-pulse" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <p className="text-xs text-zinc-400 dark:text-zinc-600 py-4 text-center">
          No tickers yet ·{" "}
          <Link href="/screener" className="text-sky-600 dark:text-sky-400 hover:underline">
            browse the screener
          </Link>
        </p>
      ) : (
        <div className="space-y-0.5">
          {shown.map((t) => {
            const q = quotes[t];
            const sig = signalByTicker[t];
            const up = (q?.change_pct ?? 0) >= 0;
            return (
              <Link
                key={t}
                href={`/signals/${t}`}
                className="flex items-center gap-3 px-2 py-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors"
              >
                <span className="font-mono font-semibold text-sm text-zinc-800 dark:text-zinc-200 w-12 shrink-0">
                  {t}
                </span>
                {q?.spark && (
                  <Sparkline data={q.spark} color={up ? "#34d399" : "#f87171"} width={56} />
                )}
                <div className="flex-1" />
                <span
                  className={cn(
                    "font-mono text-xs w-16 text-right shrink-0",
                    up ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
                  )}
                >
                  {q ? signedPct(q.change_pct, 1) : "—"}
                </span>
                {sig ? (
                  <DirectionBadge direction={sig.direction} />
                ) : (
                  <span className="w-12 text-right text-[11px] text-zinc-400 dark:text-zinc-600">
                    —
                  </span>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </Card>
  );
}
