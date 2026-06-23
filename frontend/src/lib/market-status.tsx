"use client";

import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import { getClientSessionPhase } from "@/lib/utils";
import type { MarketStatus, SessionPhase } from "@/lib/types";

/**
 * ── Global market status (single source of truth) ─────────────────────────────
 *
 * The whole app shares ONE poll of `/market-data/status` via this context.
 * `isOpen` is true during active sessions (pre-market, regular, after-hours)
 * — all components gate their live polling on this flag. OVERNIGHT is excluded
 * (no meaningful data flows 20:00–04:00 ET).
 */

interface MarketStatusValue {
  status: MarketStatus | undefined;
  /** True during pre-market, regular, or after-hours (excludes overnight). */
  isOpen: boolean;
  /** Specific session phase for display (badge label). */
  sessionPhase: SessionPhase;
  /** True when the session is open but the live feed has stalled/died — the UI
   *  should show "DELAYED" instead of a misleading "LIVE". False when unknown. */
  feedStale: boolean;
  /** Next regular open ISO (holiday-aware) when closed; null when open or unknown. */
  nextOpen: string | null;
  isLoading: boolean;
}

const MarketStatusContext = createContext<MarketStatusValue | null>(null);

const ACTIVE_PHASES: ReadonlySet<SessionPhase> = new Set(["PRE_MARKET", "REGULAR", "AFTER_HOURS"]);

export function MarketStatusProvider({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useQuery<MarketStatus>({
    queryKey: ["marketStatus"],
    queryFn: () => marketData.status(),
    refetchInterval: 60_000,
    // Keep polling while the tab is backgrounded so the badge (and every hook
    // gated on `isOpen`) is already correct on refocus, rather than lagging a
    // full interval across an open/close transition.
    refetchIntervalInBackground: true,
    staleTime: 50_000,
  });

  const fallbackPhase = getClientSessionPhase();
  const isOpen = data?.market_active ?? ACTIVE_PHASES.has(fallbackPhase);
  const sessionPhase: SessionPhase = data?.session_phase ?? fallbackPhase;
  // Regular session per the calendar, but the live feed has stopped advancing →
  // the data is stale even though the market is "open". Only asserted with real
  // backend data (the client fallback can't observe the feed).
  const feedStale = data ? data.session_open && !data.feed_live : false;
  const nextOpen = data?.next_open ?? null;

  return (
    <MarketStatusContext.Provider
      value={{ status: data, isOpen, sessionPhase, feedStale, nextOpen, isLoading }}
    >
      {children}
    </MarketStatusContext.Provider>
  );
}

export function useMarketStatus(): MarketStatusValue {
  const ctx = useContext(MarketStatusContext);
  if (ctx === null) {
    const phase = getClientSessionPhase();
    return {
      status: undefined,
      isOpen: ACTIVE_PHASES.has(phase),
      sessionPhase: phase,
      feedStale: false,
      nextOpen: null,
      isLoading: false,
    };
  }
  return ctx;
}
