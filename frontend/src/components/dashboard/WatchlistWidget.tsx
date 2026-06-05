"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Star, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { Sparkline } from "@/components/ui/Sparkline";
import { MOCK_UNIVERSE, MOCK_SIGNALS } from "@/lib/mock";
import { signedPct } from "@/lib/utils";

// Same store the /watchlist page reads & writes, so the two stay in sync.
const KEY = "penguinai_watchlist";
const DEFAULT = ["NVDA", "TSLA", "AAPL", "PLTR"];
const MAX_ROWS = 6;

export function WatchlistWidget() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) || "null");
      setTickers(Array.isArray(saved) && saved.length ? saved : DEFAULT);
    } catch {
      setTickers(DEFAULT);
    }
    setReady(true);
  }, []);

  const rows = tickers.slice(0, MAX_ROWS).map((t) => {
    const u = MOCK_UNIVERSE.find((x) => x.ticker === t);
    const sig = MOCK_SIGNALS.find((x) => x.ticker === t);
    return {
      ticker: t,
      change_pct: u?.change_pct,
      direction: u?.direction ?? ("NEUTRAL" as const),
      spark: sig?.spark,
    };
  });

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
      ) : rows.length === 0 ? (
        <p className="text-xs text-zinc-400 dark:text-zinc-600 py-4 text-center">
          No tickers yet ·{" "}
          <Link href="/screener" className="text-sky-600 dark:text-sky-400 hover:underline">
            browse the screener
          </Link>
        </p>
      ) : (
        <div className="space-y-0.5">
          {rows.map((r) => {
            const up = (r.change_pct ?? 0) >= 0;
            return (
              <Link
                key={r.ticker}
                href={`/signals/${r.ticker}`}
                className="flex items-center gap-3 px-2 py-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors"
              >
                <span className="font-mono font-semibold text-sm text-zinc-800 dark:text-zinc-200 w-12 shrink-0">
                  {r.ticker}
                </span>
                {r.spark ? (
                  <Sparkline data={r.spark} color={up ? "#34d399" : "#f87171"} width={64} className="flex-1" />
                ) : (
                  <span className="flex-1" />
                )}
                <span
                  className={`font-mono text-xs w-14 text-right shrink-0 ${
                    up ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
                  }`}
                >
                  {r.change_pct != null ? signedPct(r.change_pct, 1) : "—"}
                </span>
                <DirectionBadge direction={r.direction} />
              </Link>
            );
          })}
        </div>
      )}
    </Card>
  );
}
