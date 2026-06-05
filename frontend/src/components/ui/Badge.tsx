import { cn } from "@/lib/utils";
import type { Direction } from "@/lib/types";

const DIR: Record<Direction, string> = {
  LONG: "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  SHORT: "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30",
  NEUTRAL:
    "text-zinc-600 dark:text-zinc-400 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50",
};

export function DirectionBadge({ direction, className }: { direction: Direction; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border leading-none",
        DIR[direction],
        className
      )}
    >
      {direction}
    </span>
  );
}
