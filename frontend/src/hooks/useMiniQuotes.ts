"use client";

import { useQuery } from "@tanstack/react-query";
import { marketData } from "@/lib/api";
import { useMarketStatus } from "@/lib/market-status";
import type { MiniQuote } from "@/lib/types";

export function useMiniQuotes(tickers: string[]) {
  const key = [...tickers].sort().join(",");
  const { isOpen } = useMarketStatus();
  const query = useQuery<Record<string, MiniQuote>>({
    queryKey: ["miniQuotes", key],
    queryFn: async () => {
      if (tickers.length === 0) return {};
      try {
        const { items } = await marketData.mini(tickers);
        return Object.fromEntries(items.map((q) => [q.ticker, q]));
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
