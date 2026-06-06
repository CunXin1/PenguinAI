"use client";

import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import type { Quote } from "@/lib/types";

/**
 * Fetch live quotes for `tickers` from `market_data_1min` (via /market-data/quotes)
 * and return a `ticker → Quote` map ({} when the backend is unavailable). Used to
 * overlay real prices onto demo lists so displayed prices match the database.
 */
export function useLiveQuotes(tickers: string[]) {
  const key = [...tickers].sort().join(",");
  return useQuery<Record<string, Quote>>({
    queryKey: ["quotes", key],
    queryFn: async () => {
      if (tickers.length === 0) return {};
      try {
        const { quotes } = await marketData.quotes(tickers);
        return Object.fromEntries(quotes.map((q) => [q.ticker, q]));
      } catch {
        return {};
      }
    },
    initialData: {},
    staleTime: 0, // with initialData, any non-zero staleTime suppresses the fetch
    refetchInterval: 60_000, // keep prices fresh while the page is open
  });
}
