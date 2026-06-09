"use client";

import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import { useMarketStatus } from "@/lib/market-status";

export interface TrendRow {
  ticker: string;
  price: number;
  change_pct: number;
  spark: number[];
}

const TRENDING_WATCH = [
  "NVDA", "TSLA", "AMD", "PLTR", "MSTR", "ARM", "AVGO", "MRVL",
  "MU", "META", "AMZN", "MELI", "APP", "AXON", "NFLX", "SHOP",
];

export function useTrending(limit = 6) {
  const { isOpen } = useMarketStatus();

  return useQuery<TrendRow[]>({
    queryKey: ["trending", limit],
    queryFn: async () => {
      const { items } = await marketData.mini(TRENDING_WATCH);
      if (!Array.isArray(items) || items.length === 0) return [];
      return [...items]
        .sort((a, b) => b.change_pct - a.change_pct)
        .slice(0, limit)
        .map((q) => ({ ticker: q.ticker, price: q.price, change_pct: q.change_pct, spark: q.spark }));
    },
    refetchOnMount: "always",
    refetchInterval: isOpen ? 60_000 : false,
  });
}
