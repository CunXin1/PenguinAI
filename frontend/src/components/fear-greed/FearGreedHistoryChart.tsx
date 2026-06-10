"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fearGreed as fgApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FearGreedHistoryPoint } from "@/lib/types";
import { ZONES, fgColor } from "./util";

const RANGES = [
  { key: "1M", days: 31 },
  { key: "3M", days: 93 },
  { key: "6M", days: 186 },
  { key: "1Y", days: 365 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

const H = 260;
const PAD = { top: 12, right: 40, bottom: 24, left: 8 };

function useMeasuredWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth); // measure immediately so the chart paints on first frame
    const ro = new ResizeObserver((entries) => setW(entries[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function Canvas({ points }: { points: FearGreedHistoryPoint[] }) {
  const [wrapRef, width] = useMeasuredWidth();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);

  const geom = useMemo(() => {
    if (width <= 0 || points.length === 0) return null;
    const innerW = width - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;
    const times = points.map((p) => Date.parse(p.date + "T12:00:00Z"));
    const tMin = times[0];
    const tMax = times[times.length - 1];
    const tSpan = tMax - tMin || 1;
    const xAt = (t: number) => PAD.left + ((t - tMin) / tSpan) * innerW;
    const yAt = (v: number) => PAD.top + (1 - v / 100) * innerH;

    const xs = times.map(xAt);
    const ys = points.map((p) => yAt(p.score));
    const line = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");

    const N = 6;
    const xTicks = Array.from({ length: N + 1 }, (_, k) => {
      const t = tMin + (k / N) * tSpan;
      const d = new Date(t);
      return {
        x: xAt(t),
        label: d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      };
    });

    return { innerW, innerH, xAt, yAt, xs, ys, line, xTicks };
  }, [points, width]);

  const onMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    setHoverX(e.clientX - svg.getBoundingClientRect().left);
  }, []);

  let hoverIdx: number | null = null;
  if (geom && hoverX !== null) {
    let best = 0;
    let bd = Infinity;
    for (let i = 0; i < geom.xs.length; i++) {
      const d = Math.abs(geom.xs[i] - hoverX);
      if (d < bd) {
        bd = d;
        best = i;
      }
    }
    hoverIdx = best;
  }
  const hp = hoverIdx !== null ? points[hoverIdx] : null;
  const last = points[points.length - 1];

  return (
    <div ref={wrapRef} className="relative">
      {geom && (
        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${H}`}
          width="100%"
          height={H}
          onMouseMove={onMove}
          onMouseLeave={() => setHoverX(null)}
        >
          {/* Zone bands (faint horizontal stripes) */}
          {ZONES.map((z) => {
            const yTop = geom.yAt(z.hi);
            const yBot = geom.yAt(z.lo);
            return (
              <rect
                key={z.label}
                x={PAD.left}
                y={yTop}
                width={geom.innerW}
                height={yBot - yTop}
                fill={z.hex}
                opacity={0.07}
              />
            );
          })}

          {/* Y gridlines + labels at 0/25/50/75/100 */}
          {[0, 25, 50, 75, 100].map((v) => {
            const y = geom.yAt(v);
            return (
              <g key={v}>
                <line
                  x1={PAD.left}
                  x2={width - PAD.right}
                  y1={y}
                  y2={y}
                  stroke="currentColor"
                  strokeWidth={1}
                  className="text-zinc-200/60 dark:text-zinc-800/80"
                />
                <text
                  x={width - PAD.right + 6}
                  y={y + 3}
                  fontSize={10}
                  fill="currentColor"
                  className="text-zinc-400 dark:text-zinc-500"
                  fontFamily="ui-monospace, monospace"
                >
                  {v}
                </text>
              </g>
            );
          })}

          {/* X labels */}
          {geom.xTicks.map((t, k) => (
            <text
              key={k}
              x={Math.min(Math.max(t.x, PAD.left + 4), width - PAD.right - 4)}
              y={H - 8}
              fontSize={10}
              textAnchor="middle"
              fill="currentColor"
              className="text-zinc-400 dark:text-zinc-500"
              fontFamily="ui-monospace, monospace"
            >
              {t.label}
            </text>
          ))}

          {/* Score line */}
          <path d={geom.line} fill="none" stroke="currentColor" strokeWidth={1.75} className="text-zinc-500 dark:text-zinc-300" />

          {/* Latest marker */}
          <circle
            cx={geom.xs[geom.xs.length - 1]}
            cy={geom.ys[geom.ys.length - 1]}
            r={3.5}
            fill={fgColor(last.score)}
            stroke="#fff"
            strokeWidth={1}
          />

          {/* Hover */}
          {hp && hoverIdx !== null && (
            <>
              <line
                x1={geom.xs[hoverIdx]}
                x2={geom.xs[hoverIdx]}
                y1={PAD.top}
                y2={H - PAD.bottom}
                stroke="currentColor"
                strokeWidth={1}
                strokeDasharray="3 3"
                className="text-zinc-400 dark:text-zinc-600"
              />
              <circle cx={geom.xs[hoverIdx]} cy={geom.ys[hoverIdx]} r={4} fill={fgColor(hp.score)} stroke="#fff" strokeWidth={1} />
            </>
          )}
        </svg>
      )}

      {hp && geom && hoverIdx !== null && (
        <div
          className="absolute top-1 z-10 pointer-events-none bg-zinc-900/95 text-white text-[11px] font-mono px-2.5 py-1.5 rounded-lg border border-zinc-700 whitespace-nowrap"
          style={{ left: Math.min(Math.max(geom.xs[hoverIdx], 60), width - 90) }}
        >
          <span className="text-zinc-400">{hp.date}</span>
          <span className="ml-2 font-semibold" style={{ color: fgColor(hp.score) }}>
            {Math.round(hp.score)} · {hp.rating}
          </span>
        </div>
      )}
    </div>
  );
}

export function FearGreedHistoryChart() {
  const [range, setRange] = useState<RangeKey>("1Y");
  const days = RANGES.find((r) => r.key === range)!.days;

  const { data, isLoading } = useQuery<FearGreedHistoryPoint[]>({
    queryKey: ["fgHistory", days],
    queryFn: () => fgApi.history(days),
    staleTime: 30 * 60 * 1000,
  });

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            Fear &amp; Greed Over Time
          </h3>
          <p className="text-[11px] text-zinc-500">Daily composite index · 0 = extreme fear, 100 = extreme greed</p>
        </div>
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
      </div>

      {isLoading ? (
        <div className="grid place-items-center" style={{ height: H }}>
          <Loader2 size={18} className="animate-spin text-sky-500" />
        </div>
      ) : data && data.length > 0 ? (
        <Canvas points={data} />
      ) : (
        <div className="grid place-items-center text-sm text-zinc-400 dark:text-zinc-600" style={{ height: H }}>
          No history available yet.
        </div>
      )}
    </Card>
  );
}
