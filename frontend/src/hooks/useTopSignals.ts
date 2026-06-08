"use client";

import { useQuery } from "@tanstack/react-query";
import { marketData, signals } from "@/lib/api";
import { useMarketStatus } from "@/lib/market-status";
import { MOCK_SIGNALS } from "@/lib/mock";
import type { Quote, SignalView } from "@/lib/types";

/** Evenly sample `n` points from `arr` (keeps the sparkline light). */
function downsample(arr: number[], n: number): number[] {
  if (arr.length <= n) return arr;
  const step = (arr.length - 1) / (n - 1);
  return Array.from({ length: n }, (_, i) => arr[Math.round(i * step)]);
}

/**
 * Overlay real DB data onto a signal list: latest price + session change from
 * /market-data/quotes, and a real sparkline from the 1-week /series bars. Tickers
 * without minute data keep whatever price/spark they already had (demo).
 */
async function withRealMarketData(base: SignalView[]): Promise<SignalView[]> {
  const tickers = base.map((s) => s.ticker);
  if (tickers.length === 0) return base;

  // Latest price + % change (one round-trip for all tickers).
  let quoteMap: Record<string, Quote> = {};
  try {
    const { quotes } = await marketData.quotes(tickers);
    quoteMap = Object.fromEntries(quotes.map((q) => [q.ticker, q]));
  } catch {
    /* leave prices as-is */
  }

  // Real sparkline per ticker (graceful — a failed series just keeps the demo spark).
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

/**
 * Top signals for the dashboard. Tries the live `/signals/top` endpoint and
 * transparently falls back to demo data when the backend is unavailable or
 * returns nothing — then overlays real DB prices + sparklines so the displayed
 * values match the database regardless of whether the signals are live or demo.
 */
export function useTopSignals() {
  const { isOpen } = useMarketStatus();
  return useQuery<SignalView[]>({
    queryKey: ["topSignals"],
    queryFn: async () => {
      let base: SignalView[];
      try {
        const list = await signals.getTop(60);
        base =
          Array.isArray(list) && list.length > 0
            ? list.map((s) => ({ ...s, name: s.ticker }))
            : MOCK_SIGNALS;
      } catch {
        base = MOCK_SIGNALS;
      }
      return withRealMarketData(base);
    },
    placeholderData: MOCK_SIGNALS,
    refetchOnMount: "always",
    refetchInterval: isOpen ? 60_000 : false,
  });
}
