"use client";

import { useEffect, useRef, useState } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import type { CandleBar } from "@/lib/types";

/**
 * TradingView Lightweight Charts candlestick (v5 API). The library is loaded
 * dynamically inside the effect so it never runs during SSR. Chart chrome
 * (text, grid, borders) follows the active light/dark theme; candle colors
 * stay emerald/red in both.
 */
export function CandleChart({ data, height = 360 }: { data: CandleBar[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [isDark, setIsDark] = useState(true);

  // Track the active theme so the chart can re-render its chrome on toggle.
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setIsDark(root.classList.contains("dark"));
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let chart: IChartApi | null = null;
    let disposed = false;

    const theme = isDark
      ? {
          text: "#71717a",
          grid: "rgba(63,63,70,0.25)",
          border: "#27272a",
          crosshair: "#3f3f46",
        }
      : {
          text: "#52525b",
          grid: "rgba(228,228,231,0.7)",
          border: "#e4e4e7",
          crosshair: "#a1a1aa",
        };

    import("lightweight-charts").then(({ createChart, ColorType, CandlestickSeries }) => {
      if (disposed || !el) return;

      chart = createChart(el, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: theme.text,
          fontFamily: "ui-monospace, monospace",
        },
        grid: {
          vertLines: { color: theme.grid },
          horzLines: { color: theme.grid },
        },
        rightPriceScale: { borderColor: theme.border },
        timeScale: { borderColor: theme.border, timeVisible: true, secondsVisible: false },
        crosshair: {
          horzLine: { labelBackgroundColor: theme.crosshair },
          vertLine: { labelBackgroundColor: theme.crosshair },
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
  }, [data, isDark]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
