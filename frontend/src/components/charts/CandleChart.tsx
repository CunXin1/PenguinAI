"use client";

import { useEffect, useRef } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import type { CandleBar } from "@/lib/types";

/**
 * TradingView Lightweight Charts candlestick (v5 API). The library is loaded
 * dynamically inside the effect so it never runs during SSR.
 */
export function CandleChart({ data, height = 360 }: { data: CandleBar[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let chart: IChartApi | null = null;
    let disposed = false;

    import("lightweight-charts").then(({ createChart, ColorType, CandlestickSeries }) => {
      if (disposed || !el) return;

      chart = createChart(el, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "#71717a",
          fontFamily: "ui-monospace, monospace",
        },
        grid: {
          vertLines: { color: "rgba(63,63,70,0.25)" },
          horzLines: { color: "rgba(63,63,70,0.25)" },
        },
        rightPriceScale: { borderColor: "#27272a" },
        timeScale: { borderColor: "#27272a", timeVisible: true, secondsVisible: false },
        crosshair: {
          horzLine: { labelBackgroundColor: "#3f3f46" },
          vertLine: { labelBackgroundColor: "#3f3f46" },
        },
      });

      const series: ISeriesApi<"Candlestick"> = chart.addSeries(CandlestickSeries, {
        upColor: "#10b981",
        downColor: "#ef4444",
        borderUpColor: "#10b981",
        borderDownColor: "#ef4444",
        wickUpColor: "#10b981",
        wickDownColor: "#ef4444",
      });

      series.setData(data as Parameters<typeof series.setData>[0]);
      chart.timeScale().fitContent();
    });

    return () => {
      disposed = true;
      chart?.remove();
    };
  }, [data]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
