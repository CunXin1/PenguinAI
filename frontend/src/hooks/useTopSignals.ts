"use client";

import { useQuery } from "@tanstack/react-query";
import { marketData, signals } from "@/lib/api";
import { useMarketStatus } from "@/lib/market-status";
import type { Quote, SignalView } from "@/lib/types";

/** Evenly sample `n` points from `arr` (keeps the sparkline light). */
function downsample(arr: number[], n: number): number[] {
  if (arr.length <= n) return arr;
  const step = (arr.length - 1) / (n - 1);
  return Array.from({ length: n }, (_, i) => arr[Math.round(i * step)]);
}

/**
 * Overlay real DB data onto a signal list: latest price + session change from
 * /market-data/quotes, and a real sparkline from the 1-week /series bars.
 */
async function withRealMarketData(base: SignalView[]): Promise<SignalView[]> {
  const tickers = base.map((s) => s.ticker);
  if (tickers.length === 0) return base;

  let quoteMap: Record<string, Quote> = {};
  try {
    const { quotes } = await marketData.quotes(tickers);
    quoteMap = Object.fromEntries(quotes.map((q) => [q.ticker, q]));
  } catch {
    /* leave prices as-is */
  }

  const sparkPairs = await Promise.all(
    tickers.map(async (t): Promise<readonly [string, number[] | null]> => {
      try {
        const { bars } = await marketData.series(t, "1W");
        const closes = bars.map((b) => b.close);
        return [t, closes.length >= 2 ? downsample(closes, 24) : null];
      } catch {
        return [t, null];
      }
    })
  );
  const sparkMap = Object.fromEntries(sparkPairs);

  return base.map((s) => {
    const q = quoteMap[s.ticker];
    const spark = sparkMap[s.ticker];
    return {
      ...s,
      ...(q ? { price: q.price, change_pct: q.change_pct } : {}),
      ...(spark ? { spark } : {}),
    };
  });
}

export function useTopSignals() {
  const { isOpen } = useMarketStatus();
  return useQuery<SignalView[]>({
    queryKey: ["topSignals"],
    queryFn: async () => {
      const list = await signals.getTop(60);
      const base =
        Array.isArray(list) && list.length > 0
          ? list.map((s) => ({ ...s, name: s.ticker }))
          : [];
      if (base.length === 0) return [];
      return withRealMarketData(base);
    },
    refetchOnMount: "always",
    refetchInterval: isOpen ? 60_000 : false,
  });
}
