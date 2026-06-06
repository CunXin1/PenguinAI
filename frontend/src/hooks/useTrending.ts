"use client";

import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import { MOCK_TRENDING } from "@/lib/mock";

export interface TrendRow {
  ticker: string;
  price: number;
  change_pct: number;
}

/**
 * Liquid, volatile names that have minute data in `market_data_1min`
 * (Nasdaq-100 subset). "Trending" = today's biggest movers among these.
 */
const TRENDING_WATCH = [
  "NVDA", "TSLA", "AMD", "PLTR", "MSTR", "ARM", "AVGO", "MRVL",
  "MU", "META", "AMZN", "MELI", "APP", "AXON", "NFLX", "SHOP",
];

/**
 * Real top movers from the database (sorted by session % change), with a
 * graceful fallback to demo data when the backend is unavailable.
 */
export function useTrending(limit = 6) {
  const fallback = MOCK_TRENDING.slice(0, limit).map((t) => ({
    ticker: t.ticker,
    price: t.price,
    change_pct: t.change_pct,
  }));

  return useQuery<TrendRow[]>({
    queryKey: ["trending", limit],
    queryFn: async () => {
      try {
        const { quotes } = await marketData.quotes(TRENDING_WATCH);
        if (!Array.isArray(quotes) || quotes.length === 0) return fallback;
        return [...quotes]
          .sort((a, b) => b.change_pct - a.change_pct)
          .slice(0, limit)
          .map((q) => ({ ticker: q.ticker, price: q.price, change_pct: q.change_pct }));
      } catch {
        return fallback;
      }
    },
    initialData: fallback,
    staleTime: 0, // with initialData, any non-zero staleTime suppresses the fetch
    refetchInterval: 60_000,
  });
}
