"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import type { IChartApi } from "lightweight-charts";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FomcRatePoint } from "@/lib/types";

const RANGES = [
  { key: "1Y", years: 1 },
  { key: "3Y", years: 3 },
  { key: "5Y", years: 5 },
  { key: "10Y", years: 10 },
  { key: "ALL", years: 30 },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

function fmtRate(low: number, high: number): string {
  if (low === high) return `${low.toFixed(2)}%`;
  return `${low.toFixed(2)}–${high.toFixed(2)}%`;
}

function RateCanvas({ points, height }: { points: FomcRatePoint[]; height: number }) {
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const el = elRef.current;
    if (!el || points.length === 0) return;
    let disposed = false;

    import("lightweight-charts").then((LWC) => {
      if (disposed || !el) return;

      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }

      const chart = LWC.createChart(el, {
        autoSize: true,
        layout: {
          background: { type: LWC.ColorType.Solid, color: "transparent" },
          textColor: "#71717a",
          fontFamily: "ui-monospace, monospace",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: "rgba(63,63,70,0.22)" },
          horzLines: { color: "rgba(63,63,70,0.22)" },
        },
        rightPriceScale: {
          borderColor: "#27272a",
          scaleMargins: { top: 0.1, bottom: 0.05 },
        },
        timeScale: {
          borderColor: "#27272a",
          fixLeftEdge: true,
          fixRightEdge: true,
        },
        crosshair: {
          horzLine: { color: "#52525b", style: LWC.LineStyle.Dashed },
          vertLine: { color: "#52525b", style: LWC.LineStyle.Dashed },
        },
        handleScale: { axisPressedMouseMove: false },
      });

      const upperSeries = chart.addSeries(LWC.AreaSeries, {
        lineColor: "rgb(56, 189, 248)",
        lineWidth: 2,
        topColor: "rgba(56, 189, 248, 0.25)",
        bottomColor: "rgba(56, 189, 248, 0.02)",
        priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(2)}%` },
        crosshairMarkerRadius: 4,
        crosshairMarkerBackgroundColor: "rgb(56, 189, 248)",
      });

      const lowerSeries = chart.addSeries(LWC.AreaSeries, {
        lineColor: "rgba(56, 189, 248, 0.4)",
        lineWidth: 1,
        topColor: "rgba(56, 189, 248, 0.08)",
        bottomColor: "transparent",
        priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(2)}%` },
        crosshairMarkerRadius: 0,
      });

      const upperData = points.map((p) => ({ time: p.date, value: p.rate_high }));
      const lowerData = points.map((p) => ({ time: p.date, value: p.rate_low }));
      upperSeries.setData(upperData as never);
      lowerSeries.setData(lowerData as never);

      chart.timeScale().fitContent();
      chartRef.current = chart;
    });

    return () => {
      disposed = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [points, height]);

  return <div ref={elRef} style={{ height }} />;
}

export function RateChart() {
  const [range, setRange] = useState<RangeKey>("5Y");
  const years = RANGES.find((r) => r.key === range)!.years;

  const { data: points, isLoading } = useQuery<FomcRatePoint[]>({
    queryKey: ["fomcRateHistory", years],
    queryFn: () => fomcApi.rateHistory(years),
    staleTime: 60 * 60 * 1000,
  });

  const latest = points && points.length > 0 ? points[points.length - 1] : null;
  const height = 280;

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-1">
        <div>
          <h3 className="text-sm font-semibold text-zinc-300">Federal Funds Rate</h3>
          <p className="text-[11px] text-zinc-500">
            Target range · Source: Federal Reserve (cross-verified)
          </p>
        </div>
        {latest && (
          <span className="text-sm font-semibold font-mono text-sky-400">
            {fmtRate(latest.rate_low, latest.rate_high)}
          </span>
        )}
      </div>

      <div className="flex gap-0.5 rounded-lg bg-zinc-800/60 p-0.5 w-fit mt-2 mb-3">
        {RANGES.map((r) => (
          <button
            key={r.key}
            onClick={() => setRange(r.key)}
            className={cn(
              "px-2.5 py-1 rounded-md text-xs font-semibold transition-colors",
              range === r.key
                ? "bg-zinc-700 text-white shadow-sm"
                : "text-zinc-500 hover:text-zinc-200"
            )}
          >
            {r.key}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid place-items-center" style={{ height }}>
          <span className="flex items-center gap-2 text-sm text-zinc-500">
            <Loader2 size={16} className="animate-spin text-sky-500" /> Loading…
          </span>
        </div>
      ) : points && points.length > 0 ? (
        <RateCanvas points={points} height={height} />
      ) : (
        <div className="grid place-items-center text-sm text-zinc-500" style={{ height }}>
          No rate history available.
        </div>
      )}
    </Card>
  );
}
