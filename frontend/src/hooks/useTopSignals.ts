"use client";

import { useQuery } from "@tanstack/react-query";
import { marketData, signals } from "@/lib/api";
import { useMarketStatus } from "@/lib/market-status";
import type { Quote, SignalView } from "@/lib/types";

function downsample(arr: number[], n: number): number[] {
  if (arr.length <= n) return arr;
  const step = (arr.length - 1) / (n - 1);
  return Array.from({ length: n }, (_, i) => arr[Math.round(i * step)]);
}

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
    }),
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
 * For pinned tickers missing from the pre-computed top cache, fetch each
 * individually via /signals/{ticker}.  A 202 means "computing, not ready yet"
 * — we include it as a placeholder so the tile still renders (next refetch
 * will pick up the result).  A 404 means the ticker isn't in universe — skip.
 */
async function fetchMissing(
  tickers: string[],
): Promise<SignalView[]> {
  const results = await Promise.allSettled(
    tickers.map(async (t) => {
      try {
        const s = await signals.getByTicker(t);
        return { ...s, ticker: t, name: t } as SignalView;
      } catch (err: unknown) {
        const status =
          err && typeof err === "object" && "status" in err
            ? (err as { status: number }).status
            : 0;
        if (status === 202) {
          return {
            ticker: t,
            name: t,
            direction: "NEUTRAL",
            confidence: 0,
            holding_period: "SHORT_TERM",
            _computing: true,
          } as SignalView;
        }
        return null;
      }
    }),
  );
  return results
    .map((r) => (r.status === "fulfilled" ? r.value : null))
    .filter((v): v is SignalView => v !== null);
}

export function useTopSignals(pinnedTickers?: string[]) {
  const key = pinnedTickers ? pinnedTickers.join(",") : "__all__";
  const { isOpen } = useMarketStatus();
  return useQuery<SignalView[]>({
    queryKey: ["topSignals", key],
    queryFn: async () => {
      const list = await signals.getTop(60);
      const cachedMap = new Map(
        (Array.isArray(list) ? list : []).map((s) => [
          s.ticker,
          { ...s, name: s.ticker } as SignalView,
        ]),
      );

      if (!pinnedTickers || pinnedTickers.length === 0) {
        const all = [...cachedMap.values()];
        return all.length > 0 ? withRealMarketData(all) : [];
      }

      const fromCache: SignalView[] = [];
      const missing: string[] = [];

      for (const t of pinnedTickers) {
        const cached = cachedMap.get(t);
        if (cached) {
          fromCache.push(cached);
        } else {
          missing.push(t);
        }
      }

      const fetched = missing.length > 0 ? await fetchMissing(missing) : [];
      const base = [...fromCache, ...fetched];
      if (base.length === 0) return [];

      const enriched = await withRealMarketData(base);

      // Preserve pinned order
      const byTicker = new Map(enriched.map((s) => [s.ticker, s]));
      return pinnedTickers
        .map((t) => byTicker.get(t))
        .filter((s): s is SignalView => s !== undefined);
    },
    refetchOnMount: "always",
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.some((s) => s._computing)) return 5_000;
      return isOpen ? 60_000 : false;
    },
  });
}
