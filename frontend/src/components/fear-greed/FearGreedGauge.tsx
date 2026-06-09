"use client";

import { ZONES, fgColor, fgLabel } from "./util";

// Semicircular gauge: score 0 (left) → 100 (right). angle maps 180°→0°.
const CX = 100;
const CY = 100;
const R = 80;
const STROKE = 16;

function polar(angleDeg: number, r = R): [number, number] {
  const a = (angleDeg * Math.PI) / 180;
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)];
}

function angleForScore(score: number): number {
  return 180 - (Math.max(0, Math.min(100, score)) / 100) * 180;
}

function arcPath(scoreLo: number, scoreHi: number, r = R): string {
  const [x1, y1] = polar(angleForScore(scoreLo), r);
  const [x2, y2] = polar(angleForScore(scoreHi), r);
  // angles decrease lo→hi (left→right over the top) → sweep-flag 1
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

export function FearGreedGauge({
  score,
  label,
  size = 260,
}: {
  score: number | null;
  label?: string | null;
  size?: number;
}) {
  const s = score ?? 0;
  const needle = angleForScore(s);
  const [nx, ny] = polar(needle, R - STROKE - 6);
  const color = fgColor(s);

  return (
    <div className="flex flex-col items-center" style={{ width: size }}>
      <svg viewBox="0 0 200 116" width={size} height={size * 0.58}>
        {/* Colored zone arcs */}
        {ZONES.map((z) => (
          <path
            key={z.label}
            d={arcPath(z.lo, z.hi)}
            fill="none"
            stroke={z.hex}
            strokeWidth={STROKE}
            strokeLinecap="butt"
            opacity={score == null ? 0.25 : 0.9}
          />
        ))}

        {/* Tick labels at the ends */}
        <text x="8" y="113" fontSize="9" fill="currentColor" className="text-zinc-400 dark:text-zinc-500">
          0
        </text>
        <text x="184" y="113" fontSize="9" fill="currentColor" className="text-zinc-400 dark:text-zinc-500">
          100
        </text>

        {score != null && (
          <>
            {/* Needle */}
            <line
              x1={CX}
              y1={CY}
              x2={nx}
              y2={ny}
              stroke={color}
              strokeWidth={3}
              strokeLinecap="round"
            />
            <circle cx={CX} cy={CY} r={6} fill={color} />
            <circle cx={CX} cy={CY} r={2.5} fill="#fff" />
          </>
        )}
      </svg>

      {/* Readout */}
      <div className="-mt-6 text-center">
        {score != null ? (
          <>
            <div className="text-4xl font-bold font-mono" style={{ color }}>
              {Math.round(s)}
            </div>
            <div
              className="text-sm font-semibold uppercase tracking-wider mt-0.5"
              style={{ color }}
            >
              {label ?? fgLabel(s)}
            </div>
          </>
        ) : (
          <div className="text-sm text-zinc-400 dark:text-zinc-600 mt-2">No data yet</div>
        )}
      </div>
    </div>
  );
}
