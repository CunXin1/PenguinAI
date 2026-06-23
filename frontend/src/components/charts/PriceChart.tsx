"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CandlestickChart, LineChart, Loader2 } from "lucide-react";
import type { IChartApi, ISeriesApi, MouseEventParams } from "lightweight-charts";
import { marketData } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { useMarketStatus } from "@/lib/market-status";
import { cn, money, signedPct } from "@/lib/utils";
import type { CandleBar, ChartRange, SeriesIndicatorPoint, SessionPhase } from "@/lib/types";

type SeriesType = "area" | "candles";

const PHASE_LABELS: Record<SessionPhase, string> = {
  PRE_MARKET: "Pre-Mkt",
  REGULAR: "Live",
  AFTER_HOURS: "After-Hrs",
  OVERNIGHT: "Overnight",
  CLOSED: "Closed",
};

interface RangeCfg {
  key: ChartRange;
  /** Intraday ranges show HH:MM on the axis + legend; longer ranges show the date. */
  intraday: boolean;
}

// The backend returns exactly the requested window per range (1W → 7 days,
// 1M → 30, 3M → 90, 1Y → 365), so the chart fits the whole payload to the
// viewport — clicking "1W" shows a full week, not the last few bars of it.
const RANGES: RangeCfg[] = [
  { key: "1D", intraday: true },
  { key: "1W", intraday: true },
  { key: "1M", intraday: true },
  { key: "3M", intraday: false },
  { key: "1Y", intraday: false },
];

const UP = "#10b981"; // emerald-500
const DOWN = "#f43f5e"; // rose-500
// US stock data is stored in UTC, but a US-market chart must read in exchange time
// (ET) — otherwise the axis/crosshair show e.g. 14:30 for the 09:30 ET open. Both
// the axis (lightweight-charts defaults to UTC) and our legend format in ET.
const ET = "America/New_York";
const REFRESH_MS = 15_000;
// Daily ranges (3M/1Y) barely change → cache them long so switching back is instant
// and they don't refetch on every visit.
const DAILY_STALE_MS = 5 * 60_000;

// ── Indicator catalog ─────────────────────────────────────────────────────────
// Each chip is a logical indicator mapping to one or more DB columns (from
// /series?indicators=…) and a render target: a price-pane overlay line, an
// oscillator sub-pane, or the volume histogram (which uses bar volume directly).
type IndicatorKey =
  | "vwap" | "ema12" | "ema26" | "sma20" | "sma50" | "sma200"
  | "bb" | "macd" | "rsi" | "volume";

interface IndicatorDef {
  label: string;
  cols: string[]; // DB columns to request (empty → derived from bars, e.g. volume)
  pane: "price" | "oscillator" | "volume";
  color: string; // chip accent + (single-line) series color
}

const INDICATORS: Record<IndicatorKey, IndicatorDef> = {
  vwap: { label: "VWAP", cols: ["vwap_day"], pane: "price", color: "#a855f7" },
  ema12: { label: "EMA 12", cols: ["ema_12"], pane: "price", color: "#3b82f6" },
  ema26: { label: "EMA 26", cols: ["ema_26"], pane: "price", color: "#f59e0b" },
  sma20: { label: "SMA 20", cols: ["sma_20"], pane: "price", color: "#06b6d4" },
  sma50: { label: "SMA 50", cols: ["sma_50"], pane: "price", color: "#eab308" },
  sma200: { label: "SMA 200", cols: ["sma_200"], pane: "price", color: "#ec4899" },
  bb: { label: "Bollinger", cols: ["bb_upper", "bb_mid", "bb_lower"], pane: "price", color: "#71717a" },
  macd: { label: "MACD", cols: ["macd", "macd_signal", "macd_hist"], pane: "oscillator", color: "#3b82f6" },
  rsi: { label: "RSI", cols: ["rsi_14"], pane: "oscillator", color: "#a855f7" },
  volume: { label: "Volume", cols: [], pane: "volume", color: "#71717a" },
};

// Per-range: which chips are offered, and which start enabled. Mirrors the agreed
// design — each timeframe shows indicators meaningful at its bar granularity.
const RANGE_INDICATORS: Record<ChartRange, { available: IndicatorKey[]; defaults: IndicatorKey[] }> = {
  "1D": { available: ["vwap", "ema12", "ema26", "rsi", "bb", "volume"], defaults: ["vwap"] },
  "1W": { available: ["vwap", "ema12", "ema26", "macd", "rsi", "bb", "volume"], defaults: ["vwap", "ema12", "ema26"] },
  "1M": { available: ["sma20", "sma50", "ema12", "ema26", "macd", "rsi", "bb", "volume"], defaults: ["sma20", "sma50", "macd"] },
  "3M": { available: ["sma20", "sma50", "sma200", "ema12", "ema26", "macd", "rsi", "bb", "volume"], defaults: ["sma20", "sma50", "macd", "rsi"] },
  "1Y": { available: ["sma50", "sma200", "ema12", "ema26", "macd", "rsi", "bb", "volume"], defaults: ["sma50", "sma200", "macd"] },
};

const STORE_KEY = "penguinai_chart_indicators_v1";

function loadSelections(): Partial<Record<ChartRange, IndicatorKey[]>> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(STORE_KEY) || "{}");
  } catch {
    return {};
  }
}

/** DB columns to fetch for a range = union of all its AVAILABLE chips' columns
 *  (not just the enabled ones), so toggling a chip never triggers a refetch. */
function rangeIndicatorCols(range: ChartRange): string[] {
  const cols = new Set<string>();
  for (const k of RANGE_INDICATORS[range].available) {
    for (const c of INDICATORS[k].cols) cols.add(c);
  }
  return [...cols];
}

interface SeriesData {
  bars: CandleBar[];
  indicators: Record<string, SeriesIndicatorPoint[]>;
  prev_close: number | null;
}

/** Shared query config for one range — used by both useQuery and the prefetch warm-up. */
function seriesQuery(ticker: string, range: ChartRange) {
  return {
    queryKey: ["series", ticker, range] as const,
    queryFn: async (): Promise<SeriesData> => {
      const res = await marketData.series(ticker, range, rangeIndicatorCols(range));
      return {
        bars: (res?.bars ?? []).filter(
          (b) => Number.isFinite(b.time) && Number.isFinite(b.close)
        ),
        indicators: res?.indicators ?? {},
        prev_close: res?.prev_close ?? null,
      };
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
  const { isOpen, sessionPhase } = useMarketStatus();

  // Per-range enabled indicators, persisted to localStorage (defaults on first visit).
  const [selByRange, setSelByRange] = useState<Record<ChartRange, IndicatorKey[]>>(() => {
    const saved = loadSelections();
    const out = {} as Record<ChartRange, IndicatorKey[]>;
    (Object.keys(RANGE_INDICATORS) as ChartRange[]).forEach((r) => {
      out[r] = saved[r] ?? RANGE_INDICATORS[r].defaults;
    });
    return out;
  });
  const selected = selByRange[range];

  const toggleIndicator = (k: IndicatorKey) => {
    setSelByRange((prev) => {
      const on = new Set(prev[range]);
      if (on.has(k)) on.delete(k);
      else on.add(k);
      // Keep stable ordering by the range's declared availability.
      const nextForRange = RANGE_INDICATORS[range].available.filter((a) => on.has(a));
      const next = { ...prev, [range]: nextForRange };
      try {
        window.localStorage.setItem(STORE_KEY, JSON.stringify(next));
      } catch {
        /* ignore quota / privacy-mode errors */
      }
      return next;
    });
  };

  const qc = useQueryClient();

  // Real data only — server-aggregated OHLC from the 1-min store. No mock fallback:
  // an empty result renders an explicit empty state instead of fake bars.
  const { data, isLoading, isError } = useQuery<SeriesData>({
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

  const bars = data?.bars ?? [];
  const indicators = data?.indicators ?? {};
  const prevClose = data?.prev_close ?? null;
  const hasData = bars.length > 0;
  const last = bars[bars.length - 1]?.close ?? 0;
  // Baseline is range-aware: 1D shows the intraday move vs the prior session close
  // (prev_close); every longer range shows the return over the WHOLE window — first
  // bar → last. Using prev_close for all ranges made 1W/1M/3M/1Y all report the same
  // ~1-day change (e.g. a flat −0.9%) instead of the period return.
  const periodBase = bars[0]?.open ?? last;
  const base = range === "1D" ? (prevClose ?? periodBase) : periodBase;
  const chg = base ? ((last - base) / base) * 100 : 0;
  const up = chg >= 0;
  // Live only when the market is actually open and we're on an intraday range;
  // daily ranges are historical, and a closed market shows the last close frozen.
  const intradayLive = cfg.intraday && isOpen;
  const statusLabel = cfg.intraday ? PHASE_LABELS[sessionPhase] : "Daily";

  const available = RANGE_INDICATORS[range].available;

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

      {/* Indicator chips — colored when active; act as the chart's legend */}
      <div className="flex flex-wrap gap-1 mb-2">
        {available.map((k) => {
          const on = selected.includes(k);
          const def = INDICATORS[k];
          return (
            <button
              key={k}
              onClick={() => toggleIndicator(k)}
              aria-pressed={on}
              className={cn(
                "inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium border transition-colors",
                on
                  ? "bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 border-zinc-300 dark:border-zinc-600"
                  : "text-zinc-400 dark:text-zinc-500 border-transparent hover:text-zinc-700 dark:hover:text-zinc-300"
              )}
            >
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: on ? def.color : "transparent", border: on ? undefined : `1px solid ${def.color}` }}
              />
              {def.label}
            </button>
          );
        })}
      </div>

      {hasData ? (
        <Canvas
          bars={bars}
          indicators={indicators}
          selected={selected}
          type={type}
          up={up}
          intraday={cfg.intraday}
          range={range}
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

// ── Indicator draw specs (resolved from the enabled chips) ─────────────────────
interface DrawSpec {
  id: string; // unique series id (col name, or "volume")
  kind: "line" | "hist";
  col?: string; // indicators[col] source; absent → volume (from bars)
  color: string;
  pane: number; // 0 = price pane; ≥1 = oscillator sub-pane
  lineWidth?: number;
  guides?: number[]; // horizontal reference lines (RSI 30/70)
  signedColor?: boolean; // histogram colored by sign (MACD hist)
}

/** Turn the enabled indicator keys into concrete series specs + total pane count.
 *  Oscillators each get their own sub-pane (price stays pane 0). */
function buildDrawSpecs(
  selected: IndicatorKey[]
): { specs: DrawSpec[]; paneCount: number; volumePane: number | null } {
  const specs: DrawSpec[] = [];
  let nextPane = 1;

  // Price-pane overlays first.
  for (const k of selected) {
    const def = INDICATORS[k];
    if (def.pane !== "price") continue;
    for (const col of def.cols) {
      specs.push({
        id: col,
        kind: "line",
        col,
        color: def.color,
        pane: 0,
        lineWidth: col === "bb_mid" ? 1 : col.startsWith("bb_") ? 1 : 2,
      });
    }
  }
  // Volume gets its OWN thin pane directly under price. (It used to be overlaid on
  // the bottom of the price pane, where the bars sat on top of the area fill and
  // obscured the price curve.)
  let volumePane: number | null = null;
  if (selected.includes("volume")) {
    volumePane = nextPane++;
    specs.push({ id: "volume", kind: "hist", color: INDICATORS.volume.color, pane: volumePane });
  }
  // Oscillators each in their own sub-pane.
  for (const k of selected) {
    if (INDICATORS[k].pane !== "oscillator") continue;
    const pane = nextPane++;
    if (k === "macd") {
      specs.push({ id: "macd_hist", kind: "hist", col: "macd_hist", color: "#71717a", pane, signedColor: true });
      specs.push({ id: "macd", kind: "line", col: "macd", color: "#3b82f6", pane, lineWidth: 2 });
      specs.push({ id: "macd_signal", kind: "line", col: "macd_signal", color: "#f59e0b", pane, lineWidth: 1 });
    } else if (k === "rsi") {
      specs.push({ id: "rsi_14", kind: "line", col: "rsi_14", color: "#a855f7", pane, lineWidth: 2, guides: [30, 70] });
    }
  }
  return { specs, paneCount: nextPane, volumePane };
}

// ── Chart canvas (lightweight-charts v5) ──────────────────────────────────────
function Canvas({
  bars,
  indicators,
  selected,
  type,
  up,
  intraday,
  range,
  height,
}: {
  bars: CandleBar[];
  indicators: Record<string, SeriesIndicatorPoint[]>;
  selected: IndicatorKey[];
  type: SeriesType;
  up: boolean;
  intraday: boolean;
  range: ChartRange;
  height: number;
}) {
  const elRef = useRef<HTMLDivElement>(null);
  const legendRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | ISeriesApi<"Candlestick"> | null>(null);
  // Indicator/volume overlay series, keyed by DrawSpec.id, rebuilt on each recreate.
  const indSeriesRef = useRef<Map<string, { series: ISeriesApi<"Line"> | ISeriesApi<"Histogram">; spec: DrawSpec }>>(
    new Map()
  );
  const barsRef = useRef<CandleBar[]>(bars);
  barsRef.current = bars;
  const indRef = useRef<Record<string, SeriesIndicatorPoint[]>>(indicators);
  indRef.current = indicators;
  // Identity of the data currently drawn — lets us skip redundant setData on
  // identical 15s polls so the user's pan/zoom position is never yanked.
  const sigRef = useRef("");
  const rangeRef = useRef(range);
  const [isDark, setIsDark] = useState(true);
  // Recreate the chart when the enabled indicator set changes (panes/series differ).
  const selKey = selected.join(",");

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
    // Intraday bars are precise timestamps → show in exchange time (ET).
    // Daily bars are bucketed at UTC midnight (the cagg's time_bucket origin), so
    // the UTC date IS the trading date — formatting those in ET would shift the
    // label back a day. Keep daily dates in UTC.
    return intraday
      ? d.toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          timeZone: ET,
        })
      : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
  };

  const sigOf = (bs: CandleBar[]) => {
    const lb = bs[bs.length - 1];
    return `${bs.length}:${lb?.time ?? 0}:${lb?.close ?? 0}`;
  };

  // Show the entire returned range — the payload already IS the requested window
  // (1W → a week, 1M → a month, …), so fit all of it edge to edge.
  const frameView = () => {
    chartRef.current?.timeScale()?.fitContent();
  };

  // Create chart + series. Recreated when theme / series-type / range-granularity /
  // enabled-indicator-set change.
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
        // Crosshair time label → exchange time (ET), matching the legend + axis.
        localization: { timeFormatter: (t: unknown) => fmt(t as number) },
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
          // Axis tick labels in ET too (lightweight-charts formats in UTC by
          // default). tickMarkType >= 3 is an intraday Time tick → HH:MM; lower
          // values are Year/Month/Day boundary ticks → a short date. Date labels
          // on daily ranges stay in UTC (see fmt: daily bars sit at UTC midnight,
          // so the UTC date is the trading date — ET would shift it back a day).
          tickMarkFormatter: (time: unknown, tickMarkType: number) => {
            const d = new Date((time as number) * 1000);
            return tickMarkType >= 3
              ? d.toLocaleTimeString("en-US", {
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: false,
                  timeZone: ET,
                })
              : d.toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  timeZone: intraday ? ET : "UTC",
                });
          },
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

      // Build indicator / volume / oscillator series from the enabled chips.
      const { specs, paneCount, volumePane } = buildDrawSpecs(selected);
      const map = new Map<string, { series: ISeriesApi<"Line"> | ISeriesApi<"Histogram">; spec: DrawSpec }>();
      for (const spec of specs) {
        if (spec.kind === "hist") {
          const s = chart.addSeries(
            LWC.HistogramSeries,
            spec.id === "volume"
              ? { priceFormat: { type: "volume" }, color: "rgba(113,113,122,0.5)", priceLineVisible: false, lastValueVisible: false }
              : { color: spec.color, priceLineVisible: false, lastValueVisible: false },
            spec.pane
          );
          if (spec.id === "volume") {
            // Own pane: keep a little headroom above the tallest bar so it doesn't
            // touch the divider, and let the bars sit on the pane floor.
            s.priceScale().applyOptions({ scaleMargins: { top: 0.2, bottom: 0 } });
          }
          map.set(spec.id, { series: s, spec });
        } else {
          const s = chart.addSeries(
            LWC.LineSeries,
            { color: spec.color, lineWidth: (spec.lineWidth ?? 2) as never, priceLineVisible: false, lastValueVisible: false },
            spec.pane
          );
          for (const g of spec.guides ?? []) {
            s.createPriceLine({ price: g, color: theme.border, lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true });
          }
          map.set(spec.id, { series: s, spec });
        }
      }
      indSeriesRef.current = map;

      // Give the price pane the lion's share. Volume is a thin strip; each
      // oscillator gets a medium band.
      if (paneCount > 1) {
        const panes = chart.panes();
        panes[0]?.setStretchFactor(10);
        for (let i = 1; i < paneCount; i++) {
          panes[i]?.setStretchFactor(i === volumePane ? 2 : 4);
        }
      }

      applyData(series, barsRef.current, type, up);
      applyIndicators(map, indRef.current, barsRef.current);
      sigRef.current = sigOf(barsRef.current);
      rangeRef.current = range;
      frameView();

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
      indSeriesRef.current = new Map();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDark, type, intraday, selKey]);

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
    applyIndicators(indSeriesRef.current, indicators, bars);
    if (rangeChanged) {
      rangeRef.current = range;
      // Range changed (e.g. cached 1Y↔3M with the chart still mounted): re-frame to
      // the new range's default window — never on a same-range poll.
      frameView();
    }
    const seed = bars[bars.length - 1];
    if (seed && legendRef.current) legendRef.current.innerHTML = legendHTML(seed, type, fmt(seed.time));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, indicators, type, up, range]);

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

/** Feed each indicator/volume series its data. Lines read from indicators[col];
 *  the volume histogram reads bar volume colored by candle direction; the MACD
 *  histogram is colored by sign. */
function applyIndicators(
  map: Map<string, { series: ISeriesApi<"Line"> | ISeriesApi<"Histogram">; spec: DrawSpec }>,
  indicators: Record<string, SeriesIndicatorPoint[]>,
  bars: CandleBar[]
) {
  for (const { series, spec } of map.values()) {
    if (spec.id === "volume") {
      series.setData(
        bars.map((b) => ({
          time: b.time,
          value: (b as CandleBar & { volume?: number }).volume ?? 0,
          color: b.close >= b.open ? "rgba(16,185,129,0.35)" : "rgba(244,63,94,0.35)",
        })) as Parameters<typeof series.setData>[0]
      );
      continue;
    }
    const pts = (spec.col && indicators[spec.col]) || [];
    if (spec.signedColor) {
      series.setData(
        pts.map((p) => ({
          time: p.time,
          value: p.value,
          color: p.value >= 0 ? "rgba(16,185,129,0.5)" : "rgba(244,63,94,0.5)",
        })) as Parameters<typeof series.setData>[0]
      );
    } else {
      series.setData(
        pts.map((p) => ({ time: p.time, value: p.value })) as Parameters<typeof series.setData>[0]
      );
    }
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
