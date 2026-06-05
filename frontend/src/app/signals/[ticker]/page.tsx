"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Star } from "lucide-react";
import { signals as signalApi } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { CandleChart } from "@/components/charts/CandleChart";
import { SignalCard } from "@/components/signals/SignalCard";
import { mockCandles, mockSignalDetail } from "@/lib/mock";
import { money, signedPct } from "@/lib/utils";
import type { Signal } from "@/lib/types";

interface Props {
  params: Promise<{ ticker: string }>;
}

const WL_KEY = "penguinai_watchlist";

export default function SignalDetailPage({ params }: Props) {
  const { ticker } = use(params);
  const T = ticker.toUpperCase();

  const [signal, setSignal] = useState<Signal | null>(null);
  const [live, setLive] = useState(false);
  const [watched, setWatched] = useState(false);
  const candles = useMemo(() => mockCandles(T), [T]);

  useEffect(() => {
    let active = true;
    setSignal(null);
    (async () => {
      try {
        const data = await signalApi.getByTicker(T);
        if (active) {
          setSignal(data);
          setLive(true);
        }
      } catch {
        if (active) {
          setSignal(mockSignalDetail(T));
          setLive(false);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [T]);

  const addToWatchlist = () => {
    try {
      const cur = JSON.parse(localStorage.getItem(WL_KEY) || "[]");
      const arr = Array.isArray(cur) ? cur : [];
      if (!arr.includes(T)) localStorage.setItem(WL_KEY, JSON.stringify([T, ...arr]));
      setWatched(true);
    } catch {
      setWatched(true);
    }
  };

  const last = candles[candles.length - 1]?.close ?? 0;
  const first = candles[0]?.close ?? last;
  const chg = first ? ((last - first) / first) * 100 : 0;
  const up = chg >= 0;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-300 flex items-center gap-1 w-fit transition-colors">
        <ArrowLeft size={14} /> Dashboard
      </Link>

      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold font-mono text-white">{T}</h1>
          <div className="flex items-center gap-3 mt-1">
            <span className="font-mono text-lg text-zinc-200">{money(last)}</span>
            <span className={`font-mono text-sm ${up ? "text-emerald-400" : "text-red-400"}`}>{signedPct(chg)}</span>
            <span className="text-xs text-zinc-600">· 30m bars</span>
          </div>
        </div>
        <button
          onClick={addToWatchlist}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-zinc-800 text-sm text-zinc-300 hover:bg-zinc-800/50 transition-colors"
        >
          <Star size={14} className={watched ? "text-amber-400 fill-amber-400" : ""} />
          {watched ? "Watching" : "Watch"}
        </button>
      </div>

      <Card className="p-2 sm:p-4">
        <CandleChart data={candles} />
      </Card>

      {!signal ? (
        <div className="h-56 rounded-xl bg-zinc-900/60 animate-pulse" />
      ) : (
        <SignalCard signal={signal} />
      )}

      <p className="text-xs text-zinc-600 text-center">
        {live ? "Live signal from the API." : "Demo signal & chart — connect the backend for live ML output and real bars."}
      </p>
    </div>
  );
}
