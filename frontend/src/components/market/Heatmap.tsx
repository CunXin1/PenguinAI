"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { signedPct } from "@/lib/utils";
import type { HeatmapTile } from "@/lib/types";

interface Placed {
  x: number;
  y: number;
  w: number;
  h: number;
  tile: HeatmapTile;
}

/** Squarified treemap (Bruls et al.) — lays out tiles area-proportional to value
 *  while keeping each rectangle close to square. */
function squarify(tiles: HeatmapTile[], width: number, height: number): Placed[] {
  const items = tiles
    .filter((t) => t.market_cap > 0)
    .map((t) => ({ t, v: t.market_cap }))
    .sort((a, b) => b.v - a.v);
  if (!items.length || width <= 0 || height <= 0) return [];

  const totalValue = items.reduce((s, it) => s + it.v, 0);
  const totalArea = width * height;
  const areas = items.map((it) => (it.v / totalValue) * totalArea);

  const worst = (row: number[], side: number): number => {
    const sum = row.reduce((s, a) => s + a, 0);
    const max = Math.max(...row);
    const min = Math.min(...row);
    const s2 = side * side;
    const sum2 = sum * sum;
    return Math.max((s2 * max) / sum2, sum2 / (s2 * min));
  };

  const placed: Placed[] = [];
  let x = 0;
  let y = 0;
  let w = width;
  let h = height;
  let start = 0;

  while (start < areas.length) {
    const side = Math.min(w, h);
    const row = [areas[start]];
    let end = start + 1;
    while (end < areas.length) {
      const next = [...row, areas[end]];
      if (worst(next, side) <= worst(row, side)) {
        row.push(areas[end]);
        end++;
      } else break;
    }
    const rowSum = row.reduce((s, a) => s + a, 0);
    if (w <= h) {
      const stripH = rowSum / w;
      let cx = x;
      for (let k = 0; k < row.length; k++) {
        const tileW = row[k] / stripH;
        placed.push({ x: cx, y, w: tileW, h: stripH, tile: items[start + k].t });
        cx += tileW;
      }
      y += stripH;
      h -= stripH;
    } else {
      const stripW = rowSum / h;
      let cy = y;
      for (let k = 0; k < row.length; k++) {
        const tileH = row[k] / stripW;
        placed.push({ x, y: cy, w: stripW, h: tileH, tile: items[start + k].t });
        cy += tileH;
      }
      x += stripW;
      w -= stripW;
    }
    start = end;
  }
  return placed;
}

// ── Diverging color ramp: dark slate (flat) → vivid emerald / rose (big move) ──
type RGB = [number, number, number];
const NEUTRAL: RGB = [60, 62, 68]; // neutral zinc gray for flat tiles (~zinc-700)
const G_MID: RGB = [21, 128, 61]; // emerald-700
const G_HI: RGB = [34, 197, 94]; // emerald-500
const R_MID: RGB = [190, 30, 35]; // red-700-ish
const R_HI: RGB = [244, 63, 94]; // rose-500

const mix = (a: RGB, b: RGB, t: number): RGB => [
  Math.round(a[0] + (b[0] - a[0]) * t),
  Math.round(a[1] + (b[1] - a[1]) * t),
  Math.round(a[2] + (b[2] - a[2]) * t),
];

/** % change → tile RGB. `scale` = the % that maps to full color (varies by
 *  period — ±3% for 1D, larger for 1Y). Eased so small moves still read. */
function colorFor(pct: number, scale: number): RGB {
  if (Math.abs(pct) < scale * 0.013) return NEUTRAL;
  const mag = Math.min(Math.abs(pct) / scale, 1) ** 0.62;
  const mid = pct > 0 ? G_MID : R_MID;
  const hi = pct > 0 ? G_HI : R_HI;
  return mag <= 0.5 ? mix(NEUTRAL, mid, mag / 0.5) : mix(mid, hi, (mag - 0.5) / 0.5);
}

/** CSS gradient background for a tile/card with the given % change. Exported so
 *  the index tiles share the exact same color ramp as the map. */
export function tileGradient(pct: number, scale = 3): string {
  const [r, g, b] = colorFor(pct, scale);
  const l = (v: number) => Math.min(255, v + 16);
  return `linear-gradient(155deg, rgb(${l(r)},${l(g)},${l(b)}), rgb(${r},${g},${b}))`;
}

const GAP = 3; // gutter between tiles (px)

export function Heatmap({
  tiles,
  height = 600,
  scale = 3,
}: {
  tiles: HeatmapTile[];
  height?: number;
  scale?: number;
}) {
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setWidth(e.contentRect.width);
    });
    ro.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);

  const placed = width > 0 ? squarify(tiles, width, height) : [];

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {placed.map(({ x, y, w, h, tile }) => {
        // inset by the gutter so the card background shows as a clean gap
        const left = x + GAP / 2;
        const top = y + GAP / 2;
        const tw = Math.max(0, w - GAP);
        const th = Math.max(0, h - GAP);
        const minDim = Math.min(tw, th);

        // Only label tiles big enough to read — small-cap tail stays clean color.
        const showTicker = tw >= 44 && th >= 28;
        const showPct = th >= 48 && tw >= 54;
        const showPrice = th >= 82 && tw >= 68;
        const tickerSize = Math.max(10, Math.min(minDim * 0.32, 28));

        return (
          <button
            key={tile.ticker}
            onClick={() => router.push(`/signals/${tile.ticker}`)}
            title={`${tile.ticker}${tile.name ? ` · ${tile.name}` : ""}\n$${tile.price} · ${signedPct(tile.change_pct)}`}
            className="group absolute flex flex-col items-center justify-center overflow-hidden rounded-[4px] text-center leading-none ring-1 ring-inset ring-white/5 transition-[transform,box-shadow,filter] duration-150 ease-out hover:z-20 hover:scale-[1.04] hover:ring-2 hover:ring-white/70 hover:shadow-xl hover:shadow-black/50 hover:brightness-110"
            style={{
              left,
              top,
              width: tw,
              height: th,
              background: tileGradient(tile.change_pct, scale),
            }}
          >
            {showTicker && (
              <span
                className="font-mono font-bold tracking-tight text-white"
                style={{ fontSize: tickerSize, textShadow: "0 1px 3px rgba(0,0,0,0.4)" }}
              >
                {tile.ticker}
              </span>
            )}
            {showPct && (
              <span
                className="font-mono font-medium text-white/90"
                style={{
                  fontSize: Math.max(8, tickerSize * 0.6),
                  marginTop: 2,
                  textShadow: "0 1px 2px rgba(0,0,0,0.4)",
                }}
              >
                {signedPct(tile.change_pct, showPrice ? 2 : 1)}
              </span>
            )}
            {showPrice && (
              <span
                className="font-mono text-white/65"
                style={{ fontSize: Math.max(8, tickerSize * 0.46), marginTop: 2 }}
              >
                ${tile.price}
              </span>
            )}
            <span className="sr-only">
              {tile.ticker} {tile.change_pct >= 0 ? "up" : "down"} {signedPct(tile.change_pct)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
