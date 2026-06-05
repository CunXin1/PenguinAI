"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CandlestickChart, LineChart, Loader2 } from "lucide-react";
import type { IChartApi, ISeriesApi, MouseEventParams } from "lightweight-charts";
import { marketData } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { useMarketStatus } from "@/lib/market-status";
import { cn, money, signedPct } from "@/lib/utils";
import type { CandleBar, ChartRange } from "@/lib/types";

type SeriesType = "area" | "candles";

interface RangeCfg {
  key: ChartRange;
  /** Intraday ranges show HH:MM on the axis + legend; longer ranges show the date. */
  intraday: boolean;
  /**
   * Bars shown on first paint. The rest of the range stays off-screen so there's
   * always history to drag through (and the fewer bars are visible, the wider each
   * bar → a bigger pixel pan-range even when the range itself is data-sparse).
   */
  visible: number;
}

const RANGES: RangeCfg[] = [
  { key: "1D", intraday: true, visible: 55 },
  { key: "1W", intraday: true, visible: 110 },
  { key: "1M", intraday: true, visible: 120 },
  { key: "3M", intraday: false, visible: 45 },
  { key: "1Y", intraday: false, visible: 120 },
];

const UP = "#10b981"; // emerald-500
const DOWN = "#f43f5e"; // rose-500
const REFRESH_MS = 15_000;
// Daily ranges (3M/1Y) barely change → cache them long so switching back is instant
// and they don't refetch on every visit.
const DAILY_STALE_MS = 5 * 60_000;

/** Shared query config for one range — used by both useQuery and the prefetch warm-up. */
function seriesQuery(ticker: string, range: ChartRange) {
  return {
    queryKey: ["series", ticker, range] as const,
    queryFn: async () => {
      const res = await marketData.series(ticker, range);
      return (res?.bars ?? []).filter(
        (b) => Number.isFinite(b.time) && Number.isFinite(b.close)
      );
    },
  };
}

export function PriceChart({
  ticker,
  subtitle,
  defaultRange = "1W",
  defaultType = "area",
  height = 320,
}: {
  ticker: string;
  subtitle?: string;
  defaultRange?: ChartRange;
  defaultType?: SeriesType;
  height?: number;
}) {
  const T = ticker.toUpperCase();
  const [range, setRange] = useState<ChartRange>(defaultRange);
  const [type, setType] = useState<SeriesType>(defaultType);
  const cfg = RANGES.find((r) => r.key === range)!;
  const { isOpen } = useMarketStatus();

  const qc = useQueryClient();

  // Real data only — server-aggregated OHLC from the 1-min store. No mock fallback:
  // an empty result renders an explicit empty state instead of fake bars.
  const { data, isLoading, isError } = useQuery<CandleBar[]>({
    ...seriesQuery(T, range),
    // Poll the live minute store only while the market is open AND the range is
    // intraday; otherwise the bars are frozen at the last close, so don't refetch.
    refetchInterval: cfg.intraday && isOpen ? REFRESH_MS : false,
    staleTime: cfg.intraday ? 0 : DAILY_STALE_MS,
    // NOTE: no keepPreviousData — showing the previous range's bars while the new
    // range loads made a range switch (e.g. 3M→1Y) render the new data at the old
    // zoom (looked "stuck on 3M"). A brief loading state + fresh fit is correct.
  });

  // Warm the cache for the other ranges on mount so switching is an instant hit —
  // especially the non-polled daily ranges, which otherwise cold-fetch on each visit.
  useEffect(() => {
    for (const r of RANGES) {
      qc.prefetchQuery({
        ...seriesQuery(T, r.key),
        staleTime: r.intraday ? REFRESH_MS : DAILY_STALE_MS,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [T]);

  const bars = data ?? [];
  const hasData = bars.length > 0;
  const last = bars[bars.length - 1]?.close ?? 0;
  const first = bars[0]?.open ?? last;
  const chg = first ? ((last - first) / first) * 100 : 0;
  const up = chg >= 0;
  // Live only when the market is actually open and we're on an intraday range;
  // daily ranges are historical, and a closed market shows the last close frozen.
  const intradayLive = cfg.intraday && isOpen;
  const statusLabel = cfg.intraday ? (isOpen ? "Live" : "Closed") : "Daily";

  return (
    <Card className="p-4 sm:p-5">
      {/* Header: symbol · price · change · live dot */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="font-bold font-mono text-zinc-900 dark:text-white">{T}</span>
            {subtitle && <span className="text-xs text-zinc-500 truncate">{subtitle}</span>}
          </div>
          <div className="flex items-baseline gap-2 mt-0.5">
            <span className="font-mono text-lg text-zinc-900 dark:text-zinc-100">
              {hasData ? money(last) : "—"}
            </span>
            {hasData && (
              <span
                className={cn(
                  "font-mono text-sm",
                  up ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
                )}
              >
                {signedPct(chg)}
              </span>
            )}
          </div>
        </div>
        {hasData && (
          <span className="flex items-center gap-1.5 text-[11px] font-medium">
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full",
                intradayLive ? "bg-emerald-500 animate-pulse" : "bg-zinc-400 dark:bg-zinc-500"
              )}
            />
            <span
              className={
                intradayLive
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-zinc-500 dark:text-zinc-400"
              }
            >
              {statusLabel}
            </span>
          </span>
        )}
      </div>

      {/* Controls: range tabs (left) · series toggle (right) */}
      <div className="flex items-center justify-between gap-2 mt-3 mb-2">
        <div className="flex gap-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-800/60 p-0.5">
          {RANGES.map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={cn(
                "px-2.5 py-1 rounded-md text-xs font-semibold transition-colors",
                range === r.key
                  ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm"
                  : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              )}
            >
              {r.key}
            </button>
          ))}
        </div>
        <div className="flex gap-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-800/60 p-0.5">
          {([
            ["area", LineChart],
            ["candles", CandlestickChart],
          ] as const).map(([t, Icon]) => (
            <button
              key={t}
              onClick={() => setType(t)}
              aria-label={t === "area" ? "Area" : "Candles"}
              title={t === "area" ? "Area" : "Candlesticks"}
              className={cn(
                "w-7 h-7 grid place-items-center rounded-md transition-colors",
                type === t
                  ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm"
                  : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              )}
            >
              <Icon size={14} />
            </button>
          ))}
        </div>
      </div>

      {hasData ? (
        <Canvas
        bars={bars}
        type={type}
        up={up}
        intraday={cfg.intraday}
        range={range}
        visible={cfg.visible}
        height={height}
      />
      ) : (
        <div
          className="grid place-items-center text-sm text-zinc-400 dark:text-zinc-600"
          style={{ height }}
        >
          {isError ? (
            `Couldn't load ${T} price data.`
          ) : isLoading ? (
            <span className="flex items-center gap-2">
              <Loader2 size={16} className="animate-spin text-sky-500" /> Loading {T}…
            </span>
          ) : (
            `No price data for ${T} yet.`
          )}
        </div>
      )}
    </Card>
  );
}

// ── Chart canvas (lightweight-charts v5) ──────────────────────────────────────
function Canvas({
  bars,
  type,
  up,
  intraday,
  range,
  visible,
  height,
}: {
  bars: CandleBar[];
  type: SeriesType;
  up: boolean;
  intraday: boolean;
  range: ChartRange;
  visible: number;
  height: number;
}) {
  const elRef = useRef<HTMLDivElement>(null);
  const legendRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | ISeriesApi<"Candlestick"> | null>(null);
  const barsRef = useRef<CandleBar[]>(bars);
  barsRef.current = bars;
  // Identity of the data currently drawn — lets us skip redundant setData on
  // identical 15s polls so the user's pan/zoom position is never yanked.
  const sigRef = useRef("");
  const rangeRef = useRef(range);
  const [isDark, setIsDark] = useState(true);

  // Track theme so chart chrome follows the light/dark toggle.
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setIsDark(root.classList.contains("dark"));
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  const fmt = (t: number) => {
    const d = new Date(t * 1000);
    return intraday
      ? d.toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          timeZone: "UTC",
        })
      : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
  };

  const sigOf = (bs: CandleBar[]) => {
    const lb = bs[bs.length - 1];
    return `${bs.length}:${lb?.time ?? 0}:${lb?.close ?? 0}`;
  };

  // Open zoomed into the most recent `visible` bars, leaving older bars off-screen
  // to drag into (fixLeftEdge/fixRightEdge stop the pan exactly at the data, no blank).
  const frameView = (len: number) => {
    const ts = chartRef.current?.timeScale();
    if (!ts) return;
    if (len > visible) ts.setVisibleLogicalRange({ from: len - visible, to: len - 1 });
    else ts.fitContent(); // fewer bars than the window → just show them all
  };

  // Create chart + series. Recreated when theme / series-type / range-granularity change.
  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    let disposed = false;

    const theme = isDark
      ? { text: "#71717a", grid: "rgba(63,63,70,0.22)", border: "#27272a", crosshair: "#52525b" }
      : { text: "#52525b", grid: "rgba(228,228,231,0.7)", border: "#e4e4e7", crosshair: "#a1a1aa" };

    import("lightweight-charts").then((LWC) => {
      if (disposed || !el) return;
      const chart = LWC.createChart(el, {
        autoSize: true,
        layout: {
          background: { type: LWC.ColorType.Solid, color: "transparent" },
          textColor: theme.text,
          fontFamily: "ui-monospace, monospace",
          attributionLogo: false,
        },
        grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
        rightPriceScale: { borderColor: theme.border, scaleMargins: { top: 0.12, bottom: 0.08 } },
        timeScale: {
          borderColor: theme.border,
          timeVisible: intraday,
          secondsVisible: false,
          // Clamp scrolling to the data so you can't pan into blank gutters,
          // but DON'T fitContent — leaving bars off-screen is what makes the
          // chart pannable left/right (fitContent + fixed edges = locked).
          fixLeftEdge: true,
          fixRightEdge: true,
          rightOffset: 4,
        },
        crosshair: {
          mode: LWC.CrosshairMode.Magnet,
          horzLine: { labelBackgroundColor: theme.crosshair },
          vertLine: { labelBackgroundColor: theme.crosshair },
        },
        // Horizontal drag = PAN the time window (scroll through history), never zoom.
        handleScroll: {
          mouseWheel: false, // let the page scroll normally when the cursor is over the chart
          pressedMouseMove: true, // drag the chart body → slide the visible time range
          horzTouchDrag: true,
          vertTouchDrag: false,
        },
        handleScale: {
          mouseWheel: false, // no wheel-zoom
          pinch: true, // pinch-to-zoom on touch only
          axisPressedMouseMove: false, // dragging the time/price axis must NOT scale (zoom) it
        },
      });
      chartRef.current = chart;

      const series =
        type === "candles"
          ? chart.addSeries(LWC.CandlestickSeries, {
              upColor: UP,
              downColor: DOWN,
              borderUpColor: UP,
              borderDownColor: DOWN,
              wickUpColor: UP,
              wickDownColor: DOWN,
            })
          : chart.addSeries(LWC.AreaSeries, { lineWidth: 2, priceLineVisible: false });
      seriesRef.current = series;

      applyData(series, barsRef.current, type, up);
      sigRef.current = sigOf(barsRef.current);
      rangeRef.current = range;
      frameView(barsRef.current.length);

      // Hover read-out — update the overlay imperatively (no per-move React state).
      chart.subscribeCrosshairMove((param: MouseEventParams) => {
        const node = legendRef.current;
        if (!node) return;
        const bs = barsRef.current;
        let bar: CandleBar | undefined;
        if (param.time != null) {
          const t = param.time as unknown as number;
          bar = bs.find((b) => b.time === t) ?? bs[bs.length - 1];
        } else {
          bar = bs[bs.length - 1];
        }
        node.innerHTML = bar ? legendHTML(bar, type, fmt(bar.time)) : "";
      });

      const seed = barsRef.current[barsRef.current.length - 1];
      if (seed) legendRef.current!.innerHTML = legendHTML(seed, type, fmt(seed.time));
    });

    return () => {
      disposed = true;
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDark, type, intraday]);

  // Push new data without rebuilding the chart (so 15s polls don't flicker).
  useEffect(() => {
    const s = seriesRef.current;
    if (!s) return;
    const sig = sigOf(bars);
    const rangeChanged = rangeRef.current !== range;
    // Identical poll + same range → leave the chart (and the user's scroll) untouched.
    if (sig === sigRef.current && !rangeChanged) return;
    sigRef.current = sig;
    applyData(s, bars, type, up);
    if (rangeChanged) {
      rangeRef.current = range;
      // Range changed (e.g. cached 1Y↔3M with the chart still mounted): re-frame to
      // the new range's default window — never on a same-range poll.
      frameView(bars.length);
    }
    const seed = bars[bars.length - 1];
    if (seed && legendRef.current) legendRef.current.innerHTML = legendHTML(seed, type, fmt(seed.time));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, type, up, range]);

  return (
    <div className="relative w-full" style={{ height }}>
      <div
        ref={legendRef}
        className="absolute top-1 left-1 z-10 text-[11px] font-mono text-zinc-500 dark:text-zinc-400 pointer-events-none"
      />
      <div ref={elRef} className="w-full h-full" />
    </div>
  );
}

// ── helpers ───────────────────────────────────────────────────────────────────
function applyData(
  series: ISeriesApi<"Area"> | ISeriesApi<"Candlestick">,
  bars: CandleBar[],
  type: SeriesType,
  up: boolean
) {
  if (type === "candles") {
    series.setData(
      bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })) as Parameters<typeof series.setData>[0]
    );
  } else {
    series.applyOptions({
      lineColor: up ? UP : DOWN,
      topColor: up ? "rgba(16,185,129,0.30)" : "rgba(244,63,94,0.30)",
      bottomColor: up ? "rgba(16,185,129,0)" : "rgba(244,63,94,0)",
    });
    series.setData(bars.map((b) => ({ time: b.time, value: b.close })) as Parameters<typeof series.setData>[0]);
  }
}

function legendHTML(bar: CandleBar, type: SeriesType, when: string): string {
  const c = bar.close >= bar.open ? "#10b981" : "#f43f5e";
  const px = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (type === "candles") {
    return (
      `<span class="opacity-60">${when}</span>&nbsp;&nbsp;` +
      `O <span style="color:${c}">${px(bar.open)}</span> ` +
      `H <span style="color:${c}">${px(bar.high)}</span> ` +
      `L <span style="color:${c}">${px(bar.low)}</span> ` +
      `C <span style="color:${c}">${px(bar.close)}</span>`
    );
  }
  return `<span class="opacity-60">${when}</span>&nbsp;&nbsp;<span style="color:${c}">$${px(bar.close)}</span>`;
}
