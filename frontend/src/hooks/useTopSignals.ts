"use client";

import { useQuery } from "@tanstack/react-query";
import { signals } from "@/lib/api";
import { MOCK_SIGNALS } from "@/lib/mock";
import type { SignalView } from "@/lib/types";

/**
 * Top signals for the dashboard. Tries the live `/signals/top` endpoint and
 * transparently falls back to demo data when the backend is unavailable or
 * returns nothing — so the UI is always populated.
 */
export function useTopSignals() {
  return useQuery<SignalView[]>({
    queryKey: ["topSignals"],
    queryFn: async () => {
      try {
        const list = await signals.getTop(60);
        if (!Array.isArray(list) || list.length === 0) return MOCK_SIGNALS;
        return list.map((s) => ({ ...s, name: s.ticker }));
      } catch {
        return MOCK_SIGNALS;
      }
    },
    initialData: MOCK_SIGNALS,
  });
}
