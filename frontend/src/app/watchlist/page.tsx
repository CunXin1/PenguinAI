"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Star, Plus, X, Search } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { ConfidenceBar } from "@/components/ui/ConfidenceBar";
import { Sparkline } from "@/components/ui/Sparkline";
import { MOCK_UNIVERSE, MOCK_SIGNALS } from "@/lib/mock";
import { money, signedPct } from "@/lib/utils";

const KEY = "penguinai_watchlist";
const DEFAULT = ["NVDA", "TSLA", "AAPL", "PLTR"];

export default function WatchlistPage() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) || "null");
      setTickers(Array.isArray(saved) ? saved : DEFAULT);
    } catch {
      setTickers(DEFAULT);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (ready) localStorage.setItem(KEY, JSON.stringify(tickers));
  }, [tickers, ready]);

  const add = (e: React.FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (t && !tickers.includes(t)) setTickers([t, ...tickers]);
    setInput("");
  };
  const remove = (t: string) => setTickers((prev) => prev.filter((x) => x !== t));

  const rows = tickers.map((t) => {
    const u = MOCK_UNIVERSE.find((x) => x.ticker === t);
    const sig = MOCK_SIGNALS.find((x) => x.ticker === t);
    return {
      ticker: t,
      name: u?.name,
      price: u?.price,
      change_pct: u?.change_pct,
      direction: u?.direction ?? ("NEUTRAL" as const),
      confidence: u?.confidence ?? 0.5,
      spark: sig?.spark,
    };
  });

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
            <Star size={20} className="text-amber-500 dark:text-amber-400" /> Watchlist
          </h1>
          <p className="text-sm text-zinc-500 mt-0.5">{ready ? tickers.length : 0} tracked · saved locally</p>
        </div>
        <form
          onSubmit={add}
          className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 focus-within:border-sky-500/60 transition-colors"
        >
          <Search size={14} className="text-zinc-500" />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Add ticker..."
            className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-28"
          />
          <button type="submit" className="text-sky-500 dark:text-sky-400 hover:text-sky-600 dark:hover:text-sky-300 transition-colors" aria-label="Add">
            <Plus size={16} />
          </button>
        </form>
      </div>

      {!ready ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 rounded-xl bg-zinc-100 dark:bg-zinc-900/60 animate-pulse" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <Card className="p-10 text-center">
          <Star size={28} className="text-zinc-300 dark:text-zinc-700 mx-auto mb-3" />
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Your watchlist is empty.</p>
          <p className="text-xs text-zinc-400 dark:text-zinc-600 mt-1">
            Add a ticker above or{" "}
            <Link href="/screener" className="text-sky-600 dark:text-sky-400 hover:text-sky-500 dark:hover:text-sky-300">
              browse the screener
            </Link>
            .
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => {
            const up = (r.change_pct ?? 0) >= 0;
            return (
              <Card key={r.ticker} className="p-3 flex items-center gap-3 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
                <Link href={`/signals/${r.ticker}`} className="flex items-center gap-3 flex-1 min-w-0">
                  <div className="w-16 shrink-0">
                    <p className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100">{r.ticker}</p>
                    <p className="text-[11px] text-zinc-500 truncate">{r.name ?? "—"}</p>
                  </div>
                  {r.spark && <Sparkline data={r.spark} color={up ? "#34d399" : "#f87171"} width={72} />}
                  <div className="flex-1" />
                  <div className="text-right w-20 shrink-0">
                    <p className="font-mono text-sm text-zinc-800 dark:text-zinc-200">{r.price != null ? money(r.price) : "—"}</p>
                    {r.change_pct != null && (
                      <p className={`font-mono text-xs ${up ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>{signedPct(r.change_pct, 1)}</p>
                    )}
                  </div>
                  <div className="w-24 shrink-0">
                    <DirectionBadge direction={r.direction} />
                    <ConfidenceBar value={r.confidence} direction={r.direction} className="mt-1.5" />
                  </div>
                </Link>
                <button
                  onClick={() => remove(r.ticker)}
                  className="text-zinc-400 dark:text-zinc-600 hover:text-red-500 dark:hover:text-red-400 transition-colors p-1 shrink-0"
                  aria-label={`Remove ${r.ticker}`}
                >
                  <X size={16} />
                </button>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
