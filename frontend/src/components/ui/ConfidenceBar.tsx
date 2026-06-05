import type { Direction } from "@/lib/types";
import { cn } from "@/lib/utils";

const FILL: Record<Direction, string> = {
  LONG: "bg-emerald-500",
  SHORT: "bg-red-500",
  NEUTRAL: "bg-zinc-500",
};

export function ConfidenceBar({
  value,
  direction = "NEUTRAL",
  className,
}: {
  value: number;
  direction?: Direction;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className={cn("h-1.5 bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden", className)}>
      <div
        className={cn("h-full rounded-full transition-all duration-700", FILL[direction])}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
