"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fearGreed as fgApi } from "@/lib/api";
import { cn, signedPct } from "@/lib/utils";
import type { VolatilityBar, VolatilitySeries } from "@/lib/types";

const RANGES = [
  { key: "1M", days: 31 },
  { key: "3M", days: 93 },
  { key: "6M", days: 186 },
  { key: "1Y", days: 365 },
  { key: "5Y", days: 1826 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

const H = 280;
const PAD = { top: 14, right: 42, bottom: 24, left: 8 };
const ACCENT = "139, 92, 246"; // violet-500 — volatility/uncertainty hue

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

function niceStep(span: number): number {
  const raw = span / 5;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  const step = n >= 5 ? 5 : n >= 2 ? 2 : 1;
  return step * mag;
}

function Canvas({ bars }: { bars: VolatilityBar[] }) {
  const [wrapRef, width] = useMeasuredWidth();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const gid = "volgrad";

  const geom = useMemo(() => {
    if (width <= 0 || bars.length === 0) return null;
    const innerW = width - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;
    const closes = bars.map((b) => b.close ?? 0);
    const rawMin = Math.min(...closes);
    const rawMax = Math.max(...closes);
    const step = niceStep(rawMax - rawMin || 1);
    const yMin = Math.max(0, Math.floor(rawMin / step) * step);
    const yMax = Math.ceil(rawMax / step) * step;

    const times = bars.map((b) => b.time * 1000);
    const tMin = times[0];
    const tMax = times[times.length - 1];
    const tSpan = tMax - tMin || 1;
    const xAt = (t: number) => PAD.left + ((t - tMin) / tSpan) * innerW;
    const yAt = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin || 1)) * innerH;

    const xs = times.map(xAt);
    const ys = closes.map(yAt);
    const line = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
    const area =
      line +
      ` L${xs[xs.length - 1].toFixed(1)},${(H - PAD.bottom).toFixed(1)}` +
      ` L${xs[0].toFixed(1)},${(H - PAD.bottom).toFixed(1)} Z`;

    const yTicks: number[] = [];
    for (let v = yMin; v <= yMax + 1e-9; v += step) yTicks.push(Number(v.toFixed(2)));

    const N = 6;
    const xTicks = Array.from({ length: N + 1 }, (_, k) => {
      const t = tMin + (k / N) * tSpan;
      const d = new Date(t);
      const years = tSpan / (365.25 * 864e5);
      return {
        x: xAt(t),
        label:
          years >= 2
            ? String(d.getFullYear())
            : d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      };
    });

    return { innerH, xAt, yAt, xs, ys, line, area, yTicks, xTicks };
  }, [bars, width]);

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
  const hb = hoverIdx !== null ? bars[hoverIdx] : null;

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
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={`rgb(${ACCENT})`} stopOpacity={0.3} />
              <stop offset="100%" stopColor={`rgb(${ACCENT})`} stopOpacity={0.02} />
            </linearGradient>
          </defs>

          {geom.yTicks.map((v) => {
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

          <path d={geom.area} fill={`url(#${gid})`} />
          <path d={geom.line} fill="none" stroke={`rgb(${ACCENT})`} strokeWidth={1.75} />

          <circle
            cx={geom.xs[geom.xs.length - 1]}
            cy={geom.ys[geom.ys.length - 1]}
            r={3.5}
            fill={`rgb(${ACCENT})`}
            stroke="#fff"
            strokeWidth={1}
          />

          {hb && hoverIdx !== null && (
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
              <circle cx={geom.xs[hoverIdx]} cy={geom.ys[hoverIdx]} r={4} fill={`rgb(${ACCENT})`} stroke="#fff" strokeWidth={1} />
            </>
          )}
        </svg>
      )}

      {hb && geom && hoverIdx !== null && (
        <div
          className="absolute top-1 z-10 pointer-events-none bg-zinc-900/95 text-white text-[11px] font-mono px-2.5 py-1.5 rounded-lg border border-zinc-700 whitespace-nowrap"
          style={{ left: Math.min(Math.max(geom.xs[hoverIdx], 60), width - 90) }}
        >
          <span className="text-zinc-400">{hb.date}</span>
          <span className="ml-2 font-semibold text-violet-300">{hb.close?.toFixed(2)}</span>
        </div>
      )}
    </div>
  );
}

export function VolatilityChart() {
  const [symbol, setSymbol] = useState<"VIX" | "VVIX">("VIX");
  const [range, setRange] = useState<RangeKey>("1Y");
  const days = RANGES.find((r) => r.key === range)!.days;

  const { data, isLoading } = useQuery<VolatilitySeries>({
    queryKey: ["volatility", symbol, days],
    queryFn: () => fgApi.volatility(symbol, days),
    staleTime: 30 * 60 * 1000,
  });

  const up = (data?.change_pct ?? 0) >= 0;

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
        <div>
          <div className="flex items-center gap-2">
            {(["VIX", "VVIX"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSymbol(s)}
                className={cn(
                  "px-2 py-0.5 rounded-md text-sm font-bold font-mono transition-colors",
                  symbol === s
                    ? "bg-violet-500/15 text-violet-600 dark:text-violet-300"
                    : "text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
                )}
              >
                {s}
              </button>
            ))}
            {data?.latest != null && (
              <span className="font-mono text-lg text-zinc-900 dark:text-zinc-100 ml-1">
                {data.latest.toFixed(2)}
              </span>
            )}
            {data?.change_pct != null && (
              <span className={cn("font-mono text-xs", up ? "text-emerald-500" : "text-red-500")}>
                {signedPct(data.change_pct)}
              </span>
            )}
          </div>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            {symbol === "VIX"
              ? "CBOE Volatility Index — expected 30-day S&P 500 volatility"
              : "VVIX — volatility of VIX (the market's uncertainty about uncertainty)"}
          </p>
        </div>
        <div className="flex gap-0.5 rounded-lg bg-zinc-100 dark:bg-zinc-800/60 p-0.5">
          {RANGES.map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={cn(
                "px-2 py-1 rounded-md text-xs font-semibold transition-colors",
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
          <Loader2 size={18} className="animate-spin text-violet-500" />
        </div>
      ) : data && data.bars.length > 0 ? (
        <Canvas bars={data.bars} />
      ) : (
        <div className="grid place-items-center text-sm text-zinc-400 dark:text-zinc-600" style={{ height: H }}>
          No {symbol} data yet.
        </div>
      )}
    </Card>
  );
}
