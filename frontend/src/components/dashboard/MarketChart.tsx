"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { marketData } from "@/lib/api";
import { mockCandles } from "@/lib/mock";
import { CandleChart } from "@/components/charts/CandleChart";
import { Card } from "@/components/ui/Card";
import { money, signedPct } from "@/lib/utils";
import type { Candle, CandleBar } from "@/lib/types";

const TICKER = "QQQ";
const REFRESH_MS = 15_000;
// 1-min bars fed by the live IBKR stream (data/ingestion/ibkr_stream.py →
// market_data_1min). Falls back to demo candles when the backend is offline.
const TIMEFRAME = "1min" as const;
const DAYS = 1;

/** Normalize an API candle (time may be ISO or unix string) to a chart bar. */
function toBar(c: Candle): CandleBar {
  const t = /^\d+$/.test(String(c.time))
    ? Number(c.time)
    : Math.floor(new Date(c.time).getTime() / 1000);
  return { time: t, open: c.open, high: c.high, low: c.low, close: c.close };
}

/** Sort ascending + dedupe by time — lightweight-charts requires strict order. */
function clean(bars: CandleBar[]): CandleBar[] {
  const byTime = new Map<number, CandleBar>();
  for (const b of bars) if (Number.isFinite(b.time)) byTime.set(b.time, b);
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

interface ChartData {
  bars: CandleBar[];
  live: boolean;
}

export function MarketChart() {
  const { data } = useQuery<ChartData>({
    queryKey: ["marketChart", TICKER],
    queryFn: async () => {
      try {
        const res = await marketData.candles(TICKER, TIMEFRAME, DAYS);
        const bars = clean((res?.candles ?? []).map(toBar));
        if (bars.length > 1) return { bars, live: true };
        return { bars: mockCandles(TICKER), live: false };
      } catch {
        return { bars: mockCandles(TICKER), live: false };
      }
    },
    initialData: { bars: mockCandles(TICKER), live: false },
    refetchInterval: REFRESH_MS,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });

  const bars = data.bars;
  const last = bars[bars.length - 1]?.close ?? 0;
  const first = bars[0]?.open ?? last;
  const chg = first ? ((last - first) / first) * 100 : 0;
  const up = chg >= 0;

  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-sky-500 dark:text-sky-400" />
            <span className="font-bold font-mono text-zinc-900 dark:text-white">{TICKER}</span>
            <span className="text-xs text-zinc-500">Invesco QQQ · 1m</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-sm text-zinc-800 dark:text-zinc-200">{money(last)}</span>
            <span className={`font-mono text-xs ${up ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
              {signedPct(chg)}
            </span>
          </div>
        </div>

        <span className="flex items-center gap-1.5 text-[11px] font-medium">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              data.live ? "bg-emerald-500 animate-pulse" : "bg-zinc-400 dark:bg-zinc-600"
            }`}
          />
          <span className={data.live ? "text-emerald-600 dark:text-emerald-400" : "text-zinc-400 dark:text-zinc-600"}>
            {data.live ? "Live · 15s" : "Demo"}
          </span>
        </span>
      </div>

      <CandleChart data={bars} height={300} />
    </Card>
  );
}
