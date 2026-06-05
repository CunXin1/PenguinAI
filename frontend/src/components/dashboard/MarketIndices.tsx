"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import { Sparkline } from "@/components/ui/Sparkline";
import { Card } from "@/components/ui/Card";
import { useMarketStatus } from "@/lib/market-status";
import { cn, money, signedPct } from "@/lib/utils";

const UP = "#10b981"; // emerald-500
const DOWN = "#f43f5e"; // rose-500

// Headline US index ETFs. Dow (DIA) isn't in the loaded dataset yet (Nasdaq-100 +
// broad ETFs only), so we show Russell 2000 (IWM) for now — swap back to
// { ticker: "DIA", name: "Dow Jones" } once DIA minute data / the IBKR stream lands.
const INDICES = [
  { ticker: "QQQ", name: "Nasdaq 100" },
  { ticker: "SPY", name: "S&P 500" },
  { ticker: "IWM", name: "Russell 2000" },
];
const SYMS = INDICES.map((i) => i.ticker);

/** Top-of-dashboard index strip: live price + 1-day % change + intraday thumbnail. */
export function MarketIndices() {
  const { isOpen } = useMarketStatus();
  const { data } = useQuery({
    queryKey: ["mini", SYMS.join(",")],
    queryFn: () => marketData.mini(SYMS),
    // Track the 1-min stream while open; freeze on the last close when shut.
    refetchInterval: isOpen ? 15_000 : false,
    staleTime: 0,
  });

  const byTicker = new Map((data?.items ?? []).map((q) => [q.ticker, q]));

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {INDICES.map((idx) => {
        const q = byTicker.get(idx.ticker);
        const has = !!q && Number.isFinite(q.price);
        const up = (q?.change_pct ?? 0) >= 0;
        const color = up ? UP : DOWN;

        return (
          <Link
            key={idx.ticker}
            href={`/signals/${idx.ticker}`}
            className="group focus:outline-none"
          >
            <Card className="p-3.5 transition-colors group-hover:border-zinc-300 dark:group-hover:border-zinc-700">
              <div className="flex items-center justify-between gap-3">
                {/* left: name · ticker · price · change */}
                <div className="min-w-0">
                  <div className="flex items-baseline gap-1.5">
                    <span className="font-semibold text-sm text-zinc-900 dark:text-white truncate">
                      {idx.name}
                    </span>
                    <span className="text-[10px] font-mono text-zinc-400 dark:text-zinc-500">
                      {idx.ticker}
                    </span>
                  </div>
                  <div className="mt-0.5 font-mono text-lg leading-tight text-zinc-900 dark:text-zinc-100">
                    {has ? money(q!.price) : "—"}
                  </div>
                  {has ? (
                    <div
                      className={cn(
                        "text-xs font-mono font-medium",
                        up
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-red-600 dark:text-red-400"
                      )}
                    >
                      {signedPct(q!.change_pct)} today
                    </div>
                  ) : (
                    <div className="text-xs text-zinc-400 dark:text-zinc-600">awaiting feed</div>
                  )}
                </div>

                {/* right: intraday thumbnail */}
                <div className="shrink-0">
                  {has && q!.spark.length > 1 ? (
                    <Sparkline data={q!.spark} color={color} width={96} height={42} fill />
                  ) : (
                    <div className="w-24 h-[42px] rounded bg-zinc-100 dark:bg-zinc-800/40" />
                  )}
                </div>
              </div>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
