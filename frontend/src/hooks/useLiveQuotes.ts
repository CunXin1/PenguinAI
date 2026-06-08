"use client";

import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import { useMarketStatus } from "@/lib/market-status";
import type { Quote } from "@/lib/types";

/**
 * Fetch live quotes for `tickers` from `market_data_1min` (via /market-data/quotes)
 * and return a `ticker → Quote` map ({} when the backend is unavailable). Used to
 * overlay real prices onto demo lists so displayed prices match the database.
 */
export function useLiveQuotes(tickers: string[]) {
  const key = [...tickers].sort().join(",");
  const { isOpen } = useMarketStatus();
  const query = useQuery<Record<string, Quote>>({
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
    placeholderData: {},
    refetchOnMount: "always",
    refetchInterval: isOpen ? 60_000 : false,
  });
  return { ...query, data: query.data ?? {} };
}
