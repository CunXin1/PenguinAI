"use client";

import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import { isUsMarketActiveNow } from "@/lib/utils";
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

const PHASE_WHEN_UNKNOWN: SessionPhase = "CLOSED";

export function MarketStatusProvider({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useQuery<MarketStatus>({
    queryKey: ["marketStatus"],
    queryFn: () => marketData.status(),
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  const isOpen = data?.market_active ?? isUsMarketActiveNow();
  const sessionPhase: SessionPhase = data?.session_phase ?? PHASE_WHEN_UNKNOWN;

  return (
    <MarketStatusContext.Provider value={{ status: data, isOpen, sessionPhase, isLoading }}>
      {children}
    </MarketStatusContext.Provider>
  );
}

export function useMarketStatus(): MarketStatusValue {
  const ctx = useContext(MarketStatusContext);
  if (ctx === null) {
    return {
      status: undefined,
      isOpen: isUsMarketActiveNow(),
      sessionPhase: PHASE_WHEN_UNKNOWN,
      isLoading: false,
    };
  }
  return ctx;
}
