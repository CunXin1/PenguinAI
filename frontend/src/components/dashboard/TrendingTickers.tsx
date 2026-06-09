"use client";

import Link from "next/link";
import { Flame } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Sparkline } from "@/components/ui/Sparkline";
import { useTrending } from "@/hooks/useTrending";
import { signedPct, money } from "@/lib/utils";

export function TrendingTickers() {
  const { data } = useTrending();

  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2 mb-3">
        <Flame size={15} className="text-orange-500 dark:text-orange-400" />
        Trending
      </h3>
      <div className="space-y-0.5">
        {data?.map((t) => {
          const up = t.change_pct >= 0;
          return (
            <Link
              key={t.ticker}
              href={`/signals/${t.ticker}`}
              className="flex items-center gap-2 px-2 py-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors"
            >
              <span className="font-mono font-semibold text-sm text-zinc-800 dark:text-zinc-200 shrink-0">{t.ticker}</span>
              <div className="flex-1 min-w-[32px] max-w-[64px]">
                <Sparkline data={t.spark} color={up ? "#34d399" : "#f87171"} width={64} height={16} />
              </div>
              <span className="font-mono text-xs text-zinc-600 dark:text-zinc-400 text-right shrink-0">{money(t.price)}</span>
              <span className={`font-mono text-xs shrink-0 text-right ${up ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                {signedPct(t.change_pct, 1)}
              </span>
            </Link>
          );
        })}
      </div>
    </Card>
  );
}
