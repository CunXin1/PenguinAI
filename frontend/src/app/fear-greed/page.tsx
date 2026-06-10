"use client";

import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { fearGreed as fgApi } from "@/lib/api";
import type { FearGreedCurrent } from "@/lib/types";
import { Card } from "@/components/ui/Card";
import { FearGreedGauge } from "@/components/fear-greed/FearGreedGauge";
import { FearGreedHistoryChart } from "@/components/fear-greed/FearGreedHistoryChart";
import { ComponentBreakdown } from "@/components/fear-greed/ComponentBreakdown";
import { VolatilityChart } from "@/components/fear-greed/VolatilityChart";
import { fgTextClass } from "@/components/fear-greed/util";

function PrevTile({ label, value }: { label: string; value?: number | null }) {
  return (
    <div className="rounded-lg bg-zinc-100/60 dark:bg-zinc-800/40 px-3 py-2.5 text-center">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      {value != null ? (
        <p className={`text-lg font-bold font-mono mt-0.5 ${fgTextClass(value)}`}>
          {Math.round(value)}
        </p>
      ) : (
        <p className="text-lg font-bold font-mono mt-0.5 text-zinc-400 dark:text-zinc-600">—</p>
      )}
    </div>
  );
}

export default function FearGreedPage() {
  const { data, isError } = useQuery<FearGreedCurrent>({
    queryKey: ["fearGreedCurrent"],
    queryFn: () => fgApi.current(),
    staleTime: 15 * 60 * 1000,
  });

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <Gauge size={20} className="text-sky-600 dark:text-sky-400" /> Fear &amp; Greed Index
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          What emotion is driving the market — composite of seven indicators, plus the VIX/VVIX volatility gauges
        </p>
      </div>

      {isError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3">
          <p className="text-sm text-red-600 dark:text-red-400">
            Couldn&apos;t load the Fear &amp; Greed index right now. Showing the last known values where available.
          </p>
        </div>
      )}

      {/* Hero: full-width gradient bar + previous-period strip */}
      <Card className="p-5 sm:p-6">
        <FearGreedGauge
          score={data?.score ?? null}
          label={data?.label}
          prevScore={data?.previous?.close}
        />

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-6 pt-5 border-t border-zinc-100 dark:border-zinc-800/80">
          <PrevTile label="Previous Close" value={data?.previous?.close} />
          <PrevTile label="1 Week Ago" value={data?.previous?.week} />
          <PrevTile label="1 Month Ago" value={data?.previous?.month} />
          <PrevTile label="1 Year Ago" value={data?.previous?.year} />
        </div>

        <p className="text-[11px] text-zinc-500 mt-3">
          {data?.updated_at
            ? `Last updated ${new Date(data.updated_at).toLocaleString()}`
            : "Awaiting first reading"}
          {data?.source === "computed" && " · estimated from VIX (CNN unavailable)"}
          {data?.source === "cnn" && " · source: CNN Business"}
        </p>
      </Card>

      {/* History chart */}
      <FearGreedHistoryChart />

      {/* Components + Volatility */}
      <div className="grid lg:grid-cols-2 gap-5">
        <ComponentBreakdown components={data?.components ?? []} />
        <VolatilityChart />
      </div>
    </div>
  );
}
