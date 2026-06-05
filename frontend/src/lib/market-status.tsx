"use client";

import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import { isUsMarketSessionNow } from "@/lib/utils";
import type { MarketStatus } from "@/lib/types";

/**
 * ── Global market open/closed state (single source of truth) ───────────────────
 *
 * The whole app shares ONE poll of `/market-data/status` (backed by
 * `backend/app/core/market_clock.py`) via this context. Every LIVE/CLOSED badge
 * and every live-poll gate reads `useMarketStatus()`, so they always agree on one
 * answer. This /status poll is also the heartbeat that lets the backend observe
 * the live feed advancing and flip CLOSED→LIVE — which is why other surfaces can
 * safely stop polling while the market is closed.
 *
 * Mount once at the app root (see app/providers.tsx), inside the QueryClientProvider.
 */

interface MarketStatusValue {
  /** Raw backend payload (undefined until the first fetch resolves). */
  status: MarketStatus | undefined;
  /** Authoritative when the backend answers; client-side ET-session fallback otherwise. */
  isOpen: boolean;
  isLoading: boolean;
}

const MarketStatusContext = createContext<MarketStatusValue | null>(null);

export function MarketStatusProvider({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useQuery<MarketStatus>({
    queryKey: ["marketStatus"],
    queryFn: () => marketData.status(),
    refetchInterval: 60_000, // heartbeat: keeps the badge fresh + drives CLOSED→LIVE
    staleTime: 30_000,
  });

  // `?? fallback` only triggers on null/undefined (no data yet / backend down) —
  // a real `market_open: false` from the backend is preserved.
  const isOpen = data?.market_open ?? isUsMarketSessionNow();

  return (
    <MarketStatusContext.Provider value={{ status: data, isOpen, isLoading }}>
      {children}
    </MarketStatusContext.Provider>
  );
}

/**
 * Read the global market-open state. Intended for use under <MarketStatusProvider>;
 * if mounted outside it, it degrades to a client-side ET-session check rather than
 * throwing (consistent with the frontend's never-crash-the-page fallback style).
 */
export function useMarketStatus(): MarketStatusValue {
  const ctx = useContext(MarketStatusContext);
  if (ctx === null) {
    return { status: undefined, isOpen: isUsMarketSessionNow(), isLoading: false };
  }
  return ctx;
}
