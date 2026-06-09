"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FomcRatePoint } from "@/lib/types";

const RANGES = [
  { key: "1Y", years: 1 },
  { key: "3Y", years: 3 },
  { key: "5Y", years: 5 },
  { key: "10Y", years: 10 },
  { key: "20Y", years: 20 },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

const CHART_H = 280;
const PAD = { top: 18, right: 64, bottom: 30, left: 14 };
const SKY = "56, 189, 248"; // tailwind sky-400

function fmtRate(low: number, high: number): string {
  if (low === high) return `${low.toFixed(2)}%`;
  return `${low.toFixed(2)}–${high.toFixed(2)}%`;
}

function formatTooltipDate(dateStr: string): string {
  const d = new Date(dateStr + "T12:00:00Z");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** Build an SVG step-after path: the value holds flat then jumps — how the fed funds rate actually moves. */
function stepPath(xs: number[], ys: number[]): string {
  if (xs.length === 0) return "";
  let d = `M${xs[0].toFixed(1)},${ys[0].toFixed(1)}`;
  for (let i = 1; i < xs.length; i++) {
    d += ` L${xs[i].toFixed(1)},${ys[i - 1].toFixed(1)} L${xs[i].toFixed(1)},${ys[i].toFixed(1)}`;
  }
  return d;
}

function useMeasuredWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setW(e.contentRect.width);
    });
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function RateCanvas({ points }: { points: FomcRatePoint[] }) {
  const [wrapRef, width] = useMeasuredWidth();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);

  const geom = useMemo(() => {
    if (width <= 0) return null;
    const allRates = points.flatMap((p) => [p.rate_low, p.rate_high]);
    const rawMin = Math.min(...allRates);
    const rawMax = Math.max(...allRates);
    const yMin = Math.max(0, Math.floor(rawMin * 2) / 2 - 0.25);
    const yMax = Math.ceil(rawMax * 2) / 2 + 0.25;

    const innerW = width - PAD.left - PAD.right;
    const innerH = CHART_H - PAD.top - PAD.bottom;

    // Time-proportional x-axis: the rate is a step function held between change
    // dates, so a flat level kept for years (e.g. 2008–2015 ZIRP) must render as a
    // long flat segment. Index-based spacing would squash it into one short step.
    const times = points.map((p) => Date.parse(p.date + "T12:00:00Z"));
    const tMin = times[0];
    const tMax = times[times.length - 1];
    const tSpan = tMax - tMin || 1;
    const xAt = (t: number) => PAD.left + ((t - tMin) / tSpan) * innerW;
    const yScale = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin || 1)) * innerH;

    const xs = times.map(xAt);
    const upperYs = points.map((p) => yScale(p.rate_high));
    const lowerYs = points.map((p) => yScale(p.rate_low));

    // Pick a y-tick step that yields ~5–7 lines.
    const span = yMax - yMin;
    const stepY = [0.25, 0.5, 1, 2, 2.5].find((s) => span / s <= 7) ?? 2.5;
    const yTicks: number[] = [];
    for (let v = Math.ceil(yMin / stepY) * stepY; v <= yMax + 1e-9; v += stepY) yTicks.push(Number(v.toFixed(2)));

    // X ticks at evenly spaced *time* positions (not data indices).
    const spanYears = tSpan / (365.25 * 864e5);
    const yearOnly = spanYears >= 4;
    const N = 6;
    const xTicks = Array.from({ length: N + 1 }, (_, k) => {
      const t = tMin + (k / N) * tSpan;
      const d = new Date(t);
      const label = yearOnly
        ? String(d.getUTCFullYear())
        : d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
      return { x: xAt(t), label };
    });

    const upperLine = stepPath(xs, upperYs);
    const lowerLine = stepPath(xs, lowerYs);

    // Closed band = upper step forward, then lower step backward.
    const last = xs.length - 1;
    let area = upperLine + ` L${xs[last].toFixed(1)},${lowerYs[last].toFixed(1)}`;
    for (let i = last; i > 0; i--) {
      area += ` L${xs[i].toFixed(1)},${lowerYs[i - 1].toFixed(1)} L${xs[i - 1].toFixed(1)},${lowerYs[i - 1].toFixed(1)}`;
    }
    area += " Z";

    return { yMin, yMax, yScale, xs, upperYs, lowerYs, yTicks, xTicks, upperLine, lowerLine, area };
  }, [points, width]);

  const handleMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    setHoverX(e.clientX - rect.left);
  }, []);

  // Active rate = most recent change at or before the cursor (step semantics).
  let hoverIdx: number | null = null;
  if (geom && hoverX !== null) {
    hoverIdx = 0;
    for (let i = 0; i < geom.xs.length; i++) {
      if (geom.xs[i] <= hoverX) hoverIdx = i;
      else break;
    }
  }
  const hoverPt = hoverIdx !== null ? points[hoverIdx] : null;
  const cursorX = geom && hoverX !== null ? Math.max(PAD.left, Math.min(hoverX, width - PAD.right)) : 0;
  const lastIdx = points.length - 1;
  const gradId = "ffr-band-grad";

  return (
    <div ref={wrapRef} className="relative">
      {geom && (
        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${CHART_H}`}
          width="100%"
          height={CHART_H}
          style={{ height: CHART_H }}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverX(null)}
        >
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={`rgb(${SKY})`} stopOpacity={0.32} />
              <stop offset="100%" stopColor={`rgb(${SKY})`} stopOpacity={0.03} />
            </linearGradient>
          </defs>

          {/* Y grid lines + labels */}
          {geom.yTicks.map((v) => {
            const y = geom.yScale(v);
            return (
              <g key={v}>
                <line
                  x1={PAD.left}
                  x2={width - PAD.right}
                  y1={y}
                  y2={y}
                  stroke="currentColor"
                  strokeWidth={1}
                  className="text-zinc-200/70 dark:text-zinc-800"
                />
                <text
                  x={width - PAD.right + 8}
                  y={y + 3.5}
                  fontSize={11}
                  fill="currentColor"
                  className="text-zinc-400 dark:text-zinc-500"
                  fontFamily="ui-monospace, monospace"
                >
                  {v.toFixed(2)}%
                </text>
              </g>
            );
          })}

          {/* X axis labels (time-spaced) */}
          {geom.xTicks.map((t, k) => (
            <text
              key={k}
              x={Math.min(Math.max(t.x, PAD.left + 6), width - PAD.right - 6)}
              y={CHART_H - 10}
              fontSize={11}
              textAnchor="middle"
              fill="currentColor"
              className="text-zinc-400 dark:text-zinc-500"
              fontFamily="ui-monospace, monospace"
            >
              {t.label}
            </text>
          ))}

          {/* Rate band */}
          <path d={geom.area} fill={`url(#${gradId})`} />

          {/* Lower bound (dashed, subtle) */}
          <path
            d={geom.lowerLine}
            fill="none"
            stroke={`rgba(${SKY}, 0.45)`}
            strokeWidth={1.25}
            strokeDasharray="4 3"
            strokeLinejoin="round"
          />

          {/* Upper bound (solid, prominent) */}
          <path
            d={geom.upperLine}
            fill="none"
            stroke={`rgb(${SKY})`}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {/* Current-rate marker at the latest point */}
          <circle cx={geom.xs[lastIdx]} cy={geom.upperYs[lastIdx]} r={5} fill={`rgba(${SKY}, 0.2)`} />
          <circle
            cx={geom.xs[lastIdx]}
            cy={geom.upperYs[lastIdx]}
            r={2.5}
            fill={`rgb(${SKY})`}
            stroke="white"
            strokeWidth={1}
            className="dark:[stroke:#18181b]"
          />

          {/* Hover crosshair — snaps to cursor, dots sit at the active rate level */}
          {hoverPt && (
            <>
              <line
                x1={cursorX}
                x2={cursorX}
                y1={PAD.top}
                y2={CHART_H - PAD.bottom}
                stroke="currentColor"
                strokeWidth={1}
                strokeDasharray="3 3"
                className="text-zinc-400 dark:text-zinc-500"
              />
              <circle cx={cursorX} cy={geom.yScale(hoverPt.rate_high)} r={3.5} fill={`rgb(${SKY})`} stroke="white" strokeWidth={1.5} className="dark:[stroke:#18181b]" />
              <circle cx={cursorX} cy={geom.yScale(hoverPt.rate_low)} r={3} fill={`rgba(${SKY}, 0.6)`} stroke="white" strokeWidth={1.25} className="dark:[stroke:#18181b]" />
            </>
          )}
        </svg>
      )}

      {/* Cursor-following tooltip */}
      {hoverPt && geom && (
        <div
          className="absolute top-1 z-10 pointer-events-none -translate-x-1/2 bg-zinc-900/95 text-white text-[11px] font-mono px-2.5 py-1.5 rounded-lg shadow-lg border border-zinc-700 whitespace-nowrap"
          style={{ left: Math.min(Math.max(cursorX, 70), width - 70) }}
        >
          <span className="text-zinc-400">since {formatTooltipDate(hoverPt.date)}</span>
          <span className="ml-2 text-sky-400 font-semibold">{fmtRate(hoverPt.rate_low, hoverPt.rate_high)}</span>
        </div>
      )}
    </div>
  );
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

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-1">
        <div>
          <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">Federal Funds Rate</h3>
          <p className="text-[11px] text-zinc-500">
            Target range · Source: Federal Reserve (cross-verified)
          </p>
        </div>
        {latest && (
          <span className="text-sm font-semibold font-mono text-sky-600 dark:text-sky-400">
            {fmtRate(latest.rate_low, latest.rate_high)}
          </span>
        )}
      </div>

      <div className="flex gap-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-800/60 p-0.5 w-fit mt-2 mb-3">
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

      {isLoading ? (
        <div className="grid place-items-center" style={{ height: CHART_H }}>
          <span className="flex items-center gap-2 text-sm text-zinc-500">
            <Loader2 size={16} className="animate-spin text-sky-500" /> Loading…
          </span>
        </div>
      ) : points && points.length > 0 ? (
        <RateCanvas points={points} />
      ) : (
        <div className="grid place-items-center text-sm text-zinc-500" style={{ height: CHART_H }}>
          No rate history available.
        </div>
      )}
    </Card>
  );
}
