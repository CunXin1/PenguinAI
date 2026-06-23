"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { marketData } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { compact, signedPct } from "@/lib/utils";
import type { KeyStats as KeyStatsData } from "@/lib/types";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-zinc-100 dark:bg-zinc-800/40 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="text-sm font-mono font-semibold text-zinc-800 dark:text-zinc-200 truncate">
        {value}
      </p>
      {hint && <p className="text-[10px] text-zinc-400 dark:text-zinc-600 truncate">{hint}</p>}
    </div>
  );
}

/** Key statistics panel — market cap, trailing P/E, average volume, 52-week range.
 *  Self-fetches by ticker (same pattern as the celebrity section); renders nothing
 *  until there is at least one real figure, so empty-data symbols stay clean. */
export function KeyStats({ ticker }: { ticker: string }) {
  const { data } = useQuery<KeyStatsData>({
    queryKey: ["keyStats", ticker],
    queryFn: () => marketData.stats(ticker),
    staleTime: 10 * 60 * 1000,
    retry: false,
  });

  if (!data) return null;

  const hasAny =
    data.market_cap != null ||
    data.week52_high != null ||
    data.pe_ratio != null ||
    data.avg_volume_30d != null;
  if (!hasAny) return null;

  // Position of the latest price within the 52-week band (0 = at low, 1 = at high).
  let rangePos: number | null = null;
  if (
    data.price != null &&
    data.week52_high != null &&
    data.week52_low != null &&
    data.week52_high > data.week52_low
  ) {
    rangePos = Math.min(
      1,
      Math.max(0, (data.price - data.week52_low) / (data.week52_high - data.week52_low)),
    );
  }

  const sectorVal = data.sector ?? data.industry ?? "—";
  const sectorHint = data.sector && data.industry ? data.industry : undefined;

  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2 mb-3">
        <BarChart3 size={15} className="text-sky-500" />
        Key Statistics
      </h3>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat
          label="Market Cap"
          value={data.market_cap != null ? `$${compact(data.market_cap)}` : "—"}
        />
        <Stat
          label="P/E (TTM)"
          value={data.pe_ratio != null ? data.pe_ratio.toFixed(2) : "—"}
          hint={data.ttm_eps != null ? `EPS $${data.ttm_eps.toFixed(2)}` : undefined}
        />
        <Stat
          label="Avg Vol (30d)"
          value={data.avg_volume_30d != null ? compact(data.avg_volume_30d) : "—"}
          hint={data.last_volume != null ? `last ${compact(data.last_volume)}` : undefined}
        />
        <Stat label="Sector" value={sectorVal} hint={sectorHint} />
      </div>

      {rangePos != null && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-[11px] text-zinc-500 mb-1.5">
            <span>
              52W Low{" "}
              <span className="font-mono text-zinc-700 dark:text-zinc-300">
                ${data.week52_low!.toFixed(2)}
              </span>
            </span>
            <span>
              52W High{" "}
              <span className="font-mono text-zinc-700 dark:text-zinc-300">
                ${data.week52_high!.toFixed(2)}
              </span>
            </span>
          </div>
          <div className="relative h-1.5 rounded-full bg-gradient-to-r from-red-500/40 via-zinc-400/40 to-emerald-500/40">
            <div
              className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-sky-500 border-2 border-white dark:border-zinc-900 shadow"
              style={{ left: `${rangePos * 100}%` }}
              title={data.price != null ? `$${data.price.toFixed(2)}` : undefined}
            />
          </div>
          {data.pct_from_high != null && (
            <p className="text-[10px] text-zinc-400 dark:text-zinc-600 mt-1.5">
              {signedPct(data.pct_from_high, 1)} from 52-week high
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
