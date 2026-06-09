"use client";

import { useMarketStatus } from "@/lib/market-status";
import { cn } from "@/lib/utils";
import type { SessionPhase } from "@/lib/types";

const PHASE_LABEL: Record<SessionPhase, string> = {
  PRE_MARKET: "PRE-MKT",
  REGULAR: "LIVE",
  AFTER_HOURS: "AFTER-HRS",
  OVERNIGHT: "OVERNIGHT",
  CLOSED: "CLOSED",
};

export function MarketStatusBadge({ className }: { className?: string }) {
  const { isOpen, sessionPhase } = useMarketStatus();
  const label = PHASE_LABEL[sessionPhase];

  return (
    <span
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 min-w-[5.25rem]",
        isOpen
          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
          : "bg-zinc-500/10 text-zinc-500 dark:text-zinc-400 ring-zinc-500/20",
        className
      )}
      title={isOpen ? `US market: ${label}` : "US market closed"}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          isOpen ? "bg-emerald-500 animate-pulse" : "bg-zinc-400 dark:bg-zinc-500"
        )}
      />
      {label}
    </span>
  );
}
