"use client";

import { useEffect, useState } from "react";
import { signals } from "@/lib/api";
import type { SignalListItem } from "@/lib/types";

const DIRECTION_COLOR = {
  LONG:    "text-emerald-400",
  SHORT:   "text-red-400",
  NEUTRAL: "text-zinc-500",
};

const DIRECTION_BG = {
  LONG:    "bg-emerald-500/10 border-emerald-500/30",
  SHORT:   "bg-red-500/10 border-red-500/30",
  NEUTRAL: "bg-zinc-800 border-zinc-700",
};

export default function HomePage() {
  const [topSignals, setTopSignals] = useState<SignalListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    signals.getTop(100)
      .then(setTopSignals)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            <span className="text-white">Penguin</span>
            <span className="text-sky-400">AI</span>
          </h1>
          <p className="text-xs text-zinc-500 mt-0.5">AI Quantitative Signal Platform</p>
        </div>
        <a href="/auth/login" className="text-sm text-zinc-400 hover:text-white transition-colors">
          Sign in
        </a>
      </div>

      {/* Top signals grid */}
      <section>
        <h2 className="text-sm font-medium text-zinc-400 mb-3 uppercase tracking-wider">
          Top Signals · Live
        </h2>

        {loading ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
            {Array.from({ length: 24 }).map((_, i) => (
              <div key={i} className="h-16 rounded-lg bg-zinc-800/60 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-2">
            {topSignals.map((s) => (
              <a
                key={s.ticker}
                href={`/signals/${s.ticker}`}
                className={`rounded-lg border p-3 cursor-pointer hover:scale-105 transition-transform ${DIRECTION_BG[s.direction]}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-bold text-white font-mono">{s.ticker}</span>
                  <span className={`text-[10px] font-semibold ${DIRECTION_COLOR[s.direction]}`}>
                    {s.direction}
                  </span>
                </div>
                <div className="h-1 bg-zinc-700/50 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      s.direction === "LONG" ? "bg-emerald-500" :
                      s.direction === "SHORT" ? "bg-red-500" : "bg-zinc-500"
                    }`}
                    style={{ width: `${Math.round(s.confidence * 100)}%` }}
                  />
                </div>
                <p className="text-[10px] text-zinc-600 mt-1 font-mono">
                  {Math.round(s.confidence * 100)}% conf
                </p>
              </a>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
