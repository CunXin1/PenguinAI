"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { ZONES, fgColor, fgLabel } from "./util";

// Smooth left→right gradient: extreme fear (red) → extreme greed (emerald).
const GRADIENT =
  "linear-gradient(90deg, #ef4444 0%, #f97316 25%, #eab308 50%, #84cc16 75%, #10b981 100%)";

const clamp = (n: number) => Math.max(0, Math.min(100, n));

function TrendChip({ score, prev }: { score: number; prev: number }) {
  const delta = score - prev;
  if (Math.abs(delta) < 0.5) {
    return (
      <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
        flat vs prev close
      </span>
    );
  }
  const up = delta > 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-semibold ${
        up ? "text-emerald-500" : "text-red-500"
      }`}
    >
      <Icon size={14} />
      {up ? "+" : ""}
      {Math.round(delta)} vs prev close
    </span>
  );
}

export function FearGreedGauge({
  score,
  label,
  prevScore,
  compact = false,
}: {
  score: number | null;
  label?: string | null;
  /** previous-close score → renders a faint "from" marker + trend chip */
  prevScore?: number | null;
  compact?: boolean;
}) {
  const has = score != null;
  const s = score ?? 0;
  const pos = clamp(s);
  const color = fgColor(s);
  const prevPos = prevScore != null ? clamp(prevScore) : null;

  return (
    <div className="w-full">
      {/* ── Header: big score + label (+ trend) ── */}
      <div className="flex items-end justify-between gap-3 mb-3">
        <div className="flex items-baseline gap-2.5">
          <span
            className={compact ? "text-3xl font-bold font-mono" : "text-5xl font-bold font-mono"}
            style={{ color: has ? color : undefined }}
          >
            {has ? Math.round(s) : "—"}
          </span>
          {!compact && has && (
            <span className="text-lg font-mono text-zinc-400 dark:text-zinc-600">/100</span>
          )}
          <span
            className={`font-semibold uppercase tracking-wider ${compact ? "text-xs" : "text-sm"}`}
            style={{ color: has ? color : undefined }}
          >
            {has ? (label ?? fgLabel(s)) : "No data"}
          </span>
        </div>
        {!compact && has && prevScore != null && <TrendChip score={s} prev={prevScore} />}
      </div>

      {/* ── Gradient bar with marker + value bubble ── */}
      <div className={compact ? "relative pt-1" : "relative pt-7"}>
        {/* Value bubble (full mode only) */}
        {!compact && has && (
          <div
            className="absolute top-0 -translate-x-1/2 transition-[left] duration-700 ease-out"
            style={{ left: `${pos}%` }}
          >
            <div
              className="px-2 py-0.5 rounded-full text-[11px] font-semibold font-mono text-white shadow-md leading-none"
              style={{ backgroundColor: color }}
            >
              {Math.round(s)}
            </div>
            <div
              className="w-2 h-2 rotate-45 mx-auto -mt-1"
              style={{ backgroundColor: color }}
            />
          </div>
        )}

        {/* Track */}
        <div
          className={`relative w-full rounded-full ${compact ? "h-2.5" : "h-3.5"}`}
          style={{ background: GRADIENT, opacity: has ? 1 : 0.3 }}
        >
          {/* Zone divider ticks at 25 / 50 / 75 */}
          {[25, 50, 75].map((t) => (
            <div
              key={t}
              className="absolute top-0 bottom-0 w-px bg-black/15 dark:bg-white/15"
              style={{ left: `${t}%` }}
            />
          ))}

          {/* Previous-close ghost marker */}
          {prevPos != null && (
            <div
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 rounded-full border border-white/70 dark:border-white/60"
              style={{
                left: `${prevPos}%`,
                width: compact ? 8 : 10,
                height: compact ? 8 : 10,
                backgroundColor: "rgba(255,255,255,0.35)",
              }}
              title={`Previous close: ${Math.round(prevScore!)}`}
            />
          )}

          {/* Current marker knob */}
          {has && (
            <div
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 rounded-full bg-white shadow-md transition-[left] duration-700 ease-out"
              style={{
                left: `${pos}%`,
                width: compact ? 14 : 18,
                height: compact ? 14 : 18,
                border: `${compact ? 3 : 4}px solid ${color}`,
              }}
            />
          )}
        </div>

        {/* Scale */}
        {compact ? (
          <div className="flex justify-between text-[9px] text-zinc-400 dark:text-zinc-600 mt-1.5 px-0.5">
            <span>Fear</span>
            <span>Greed</span>
          </div>
        ) : (
          <div className="mt-2 flex">
            {ZONES.map((z) => {
              const active = s >= z.lo && s <= z.hi;
              return (
                <div
                  key={z.label}
                  className="flex-1 text-center text-[10px] leading-tight"
                  style={{
                    color: active ? z.hex : undefined,
                    fontWeight: active ? 700 : 400,
                  }}
                >
                  <span className={active ? "" : "text-zinc-400 dark:text-zinc-600"}>
                    {z.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
