"use client";

import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import { getClientSessionPhase, isUsMarketActiveNow } from "@/lib/utils";
import type { MarketStatus, SessionPhase } from "@/lib/types";

/**
 * ── Global market status (single source of truth) ─────────────────────────────
 *
 * The whole app shares ONE poll of `/market-data/status` via this context.
 * `isOpen` is true during ANY active session (pre-market, regular, after-hours,
 * overnight) — all components gate their live polling on this flag so data
 * flows throughout extended hours.
 */

interface MarketStatusValue {
  status: MarketStatus | undefined;
  /** True during any active session (pre/regular/after/overnight) or ticks flowing. */
  isOpen: boolean;
  /** Specific session phase for display (badge label). */
  sessionPhase: SessionPhase;
  isLoading: boolean;
}

const MarketStatusContext = createContext<MarketStatusValue | null>(null);

export function MarketStatusProvider({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useQuery<MarketStatus>({
    queryKey: ["marketStatus"],
    queryFn: () => marketData.status(),
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  const fallbackPhase = getClientSessionPhase();
  const isOpen = data?.market_active ?? (fallbackPhase !== "CLOSED");
  const sessionPhase: SessionPhase = data?.session_phase ?? fallbackPhase;

  return (
    <MarketStatusContext.Provider value={{ status: data, isOpen, sessionPhase, isLoading }}>
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
      isOpen: phase !== "CLOSED",
      sessionPhase: phase,
      isLoading: false,
    };
  }
  return ctx;
}
