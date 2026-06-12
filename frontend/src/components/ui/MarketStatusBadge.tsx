"use client";

import { useMarketStatus } from "@/lib/market-status";
import { cn, formatReopen } from "@/lib/utils";
import type { SessionPhase } from "@/lib/types";

const PHASE_LABEL: Record<SessionPhase, string> = {
  PRE_MARKET: "PRE-MKT",
  REGULAR: "LIVE",
  AFTER_HOURS: "AFTER-HRS",
  OVERNIGHT: "OVERNIGHT",
  CLOSED: "CLOSED",
};

export function MarketStatusBadge({ className }: { className?: string }) {
  const { isOpen, sessionPhase, nextOpen } = useMarketStatus();
  const label = PHASE_LABEL[sessionPhase];
  // Reopen hint (pre-market 04:00 ET) only when fully CLOSED (weekend / NYSE
  // holiday), NOT during weekday OVERNIGHT — keep that phase's display unchanged.
  const reopen = sessionPhase === "CLOSED" ? formatReopen(nextOpen) : null;

  // The colored pill stays a fixed size across ALL phases (LIVE / PRE-MKT /
  // CLOSED …) so it reads consistently in the navbar; the reopen time rides
  // alongside as secondary muted text rather than inflating the pill.
  const pill = (
    <span
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 min-w-[5.25rem]",
        isOpen
          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
          : "bg-zinc-500/10 text-zinc-500 dark:text-zinc-400 ring-zinc-500/20"
      )}
      title={
        isOpen
          ? `US market: ${label}`
          : reopen
            ? `US market closed · opens ${reopen} ET`
            : "US market closed"
      }
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full shrink-0",
          isOpen ? "bg-emerald-500 animate-pulse" : "bg-zinc-400 dark:bg-zinc-500"
        )}
      />
      {label}
    </span>
  );

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      {pill}
      {reopen && (
        <span className="hidden md:inline text-[11px] text-zinc-400 dark:text-zinc-500 whitespace-nowrap">
          Opens {reopen}
        </span>
      )}
    </span>
  );
}
