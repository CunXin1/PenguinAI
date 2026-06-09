"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

interface CelebrityRingProps {
  buys: number;
  sells: number;
  holds?: number;
  size?: number;
  strokeWidth?: number;
  initials: string;
  gradientClass: string;
  image?: string;
  onSegmentClick?: (action: "BUY" | "SELL" | "HOLD") => void;
  onCenterClick?: () => void;
  selected?: boolean;
  className?: string;
}

const CX = 50;
const CY = 50;
const R = 40;

function arcPath(startAngle: number, endAngle: number): string {
  if (endAngle - startAngle >= Math.PI * 2 - 0.01) {
    return `M ${CX + R} ${CY} A ${R} ${R} 0 1 1 ${CX - R} ${CY} A ${R} ${R} 0 1 1 ${CX + R} ${CY}`;
  }
  const sx = CX + R * Math.cos(startAngle);
  const sy = CY + R * Math.sin(startAngle);
  const ex = CX + R * Math.cos(endAngle);
  const ey = CY + R * Math.sin(endAngle);
  const large = endAngle - startAngle > Math.PI ? 1 : 0;
  return `M ${sx} ${sy} A ${R} ${R} 0 ${large} 1 ${ex} ${ey}`;
}

type SegKey = "BUY" | "SELL" | "HOLD";
interface Seg {
  key: SegKey;
  count: number;
  color: string;
  hoverColor: string;
}

export function CelebrityRing({
  buys,
  sells,
  holds = 0,
  size = 100,
  strokeWidth = 12,
  initials,
  gradientClass,
  image,
  onSegmentClick,
  onCenterClick,
  selected,
  className,
}: CelebrityRingProps) {
  const [imgError, setImgError] = useState(false);
  const [hovered, setHovered] = useState<SegKey | null>(null);
  const total = buys + sells + holds;

  const allSegs: Seg[] = [
    { key: "BUY", count: buys, color: "#10b981", hoverColor: "#34d399" },
    { key: "SELL", count: sells, color: "#ef4444", hoverColor: "#f87171" },
    { key: "HOLD", count: holds, color: "#52525b", hoverColor: "#71717a" },
  ];
  const segments = allSegs.filter((s) => s.count > 0);

  const GAP = segments.length > 1 ? 0.06 : 0;
  const arcs: { seg: Seg; start: number; end: number }[] = [];
  let angle = 0;
  for (const seg of segments) {
    const sweep = (seg.count / total) * Math.PI * 2;
    arcs.push({
      seg,
      start: angle + (segments.length > 1 ? GAP / 2 : 0),
      end: angle + sweep - (segments.length > 1 ? GAP / 2 : 0),
    });
    angle += sweep;
  }

  const innerSize = (size * (2 * (R - strokeWidth / 2) - 1)) / 100;
  const fontSize = innerSize * 0.28;

  return (
    <div
      className={cn("relative", className)}
      style={{ width: size, height: size }}
    >
      <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
        <circle
          cx={CX}
          cy={CY}
          r={R}
          fill="none"
          stroke="#27272a"
          strokeWidth={strokeWidth}
        />
        {total > 0 &&
          arcs.map(({ seg, start, end }) => (
            <path
              key={seg.key}
              d={arcPath(start, end)}
              fill="none"
              stroke={hovered === seg.key ? seg.hoverColor : seg.color}
              strokeWidth={hovered === seg.key ? strokeWidth + 2 : strokeWidth}
              strokeLinecap="round"
              style={{ transition: "stroke 0.15s, stroke-width 0.15s" }}
              className={onSegmentClick ? "cursor-pointer" : ""}
              onMouseEnter={() => setHovered(seg.key)}
              onMouseLeave={() => setHovered(null)}
              onClick={(e) => {
                e.stopPropagation();
                onSegmentClick?.(seg.key);
              }}
            />
          ))}
      </svg>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onCenterClick?.();
        }}
        className={cn(
          "absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full overflow-hidden transition-all",
          selected && "ring-2 ring-sky-500 ring-offset-2 ring-offset-zinc-950",
          onCenterClick && "cursor-pointer"
        )}
        style={{ width: innerSize, height: innerSize }}
      >
        {image && !imgError ? (
          <img
            src={image}
            alt=""
            className="w-full h-full object-cover"
            onError={() => setImgError(true)}
          />
        ) : (
          <div
            className={cn(
              "w-full h-full flex items-center justify-center bg-gradient-to-br text-white font-bold select-none",
              gradientClass
            )}
            style={{ fontSize }}
          >
            {initials}
          </div>
        )}
      </button>
    </div>
  );
}
