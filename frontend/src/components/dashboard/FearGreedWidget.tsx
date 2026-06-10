"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Gauge, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fearGreed as fgApi } from "@/lib/api";
import type { FearGreedCurrent } from "@/lib/types";
import { FearGreedGauge } from "@/components/fear-greed/FearGreedGauge";
import { fgTextClass } from "@/components/fear-greed/util";

function PrevRow({ label, value }: { label: string; value?: number | null }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-zinc-500">{label}</span>
      {value != null ? (
        <span className={`font-mono font-semibold ${fgTextClass(value)}`}>
          {Math.round(value)}
        </span>
      ) : (
        <span className="text-zinc-400 dark:text-zinc-600">—</span>
      )}
    </div>
  );
}

export function FearGreedWidget() {
  const { data, isLoading } = useQuery<FearGreedCurrent>({
    queryKey: ["dashboardFearGreed"],
    queryFn: () => fgApi.current(),
    staleTime: 15 * 60 * 1000,
  });

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
          <Gauge size={15} className="text-sky-500 dark:text-sky-400" />
          Fear &amp; Greed
        </h3>
        <Link
          href="/fear-greed"
          className="text-xs text-zinc-500 hover:text-sky-600 dark:hover:text-sky-400 flex items-center gap-1 transition-colors"
        >
          Details <ArrowRight size={12} />
        </Link>
      </div>

      {isLoading ? (
        <div className="h-36 rounded bg-zinc-100 dark:bg-zinc-800/60 animate-pulse" />
      ) : (
        <>
          <div className="pt-2 pb-1">
            <FearGreedGauge
              score={data?.score ?? null}
              label={data?.label}
              prevScore={data?.previous?.close}
              compact
            />
          </div>
          <div className="space-y-1.5 mt-3 pt-3 border-t border-zinc-100 dark:border-zinc-800/80">
            <PrevRow label="1 week ago" value={data?.previous?.week} />
            <PrevRow label="1 month ago" value={data?.previous?.month} />
            <PrevRow label="1 year ago" value={data?.previous?.year} />
          </div>
          {data?.source === "computed" && (
            <p className="text-[10px] text-zinc-400 dark:text-zinc-600 mt-2 text-center">
              estimated from VIX (CNN unavailable)
            </p>
          )}
        </>
      )}
    </Card>
  );
}
