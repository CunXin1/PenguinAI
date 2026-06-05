"use client";

import { useMarketStatus } from "@/lib/market-status";
import { cn } from "@/lib/utils";

/**
 * Global market open/closed pill — green pulsing "LIVE" while open, gray "CLOSED"
 * otherwise. Reads the shared `useMarketStatus()` so it always agrees with every
 * chart's live badge and poll cadence.
 */
export function MarketStatusBadge({ className }: { className?: string }) {
  const { isOpen } = useMarketStatus();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1",
        isOpen
          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
          : "bg-zinc-500/10 text-zinc-500 dark:text-zinc-400 ring-zinc-500/20",
        className
      )}
      title={isOpen ? "US market open" : "US market closed"}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          isOpen ? "bg-emerald-500 animate-pulse" : "bg-zinc-400 dark:bg-zinc-500"
        )}
      />
      {isOpen ? "LIVE" : "CLOSED"}
    </span>
  );
}
