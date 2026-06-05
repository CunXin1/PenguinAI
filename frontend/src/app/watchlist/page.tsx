"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Star, Plus, X, Search, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { tickers as tickerApi } from "@/lib/api";
import { useWatchlist } from "@/hooks/useWatchlist";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";
import { cn, money, signedPct } from "@/lib/utils";

export default function WatchlistPage() {
  const router = useRouter();
  const { tickers, signalByTicker, add, remove, ready, isLoggedIn } = useWatchlist();
  const { data: quotes } = useLiveQuotes(tickers);
  const [input, setInput] = useState("");
  const [adding, setAdding] = useState(false);

  // Only add symbols we actually cover. Anything else navigates to the signal
  // page (which renders the UnknownSymbol view) — never silently added here.
  const onAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (!t || adding) return;
    if (tickers.includes(t)) {
      setInput("");
      return;
    }
    setAdding(true);
    try {
      const row = await tickerApi.get(t); // 404 if not in the universe
      if (!row.is_active) {
        router.push(`/signals/${t}`);
        return;
      }
      await add(t);
      setInput("");
    } catch {
      router.push(`/signals/${t}`);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
            <Star size={20} className="text-amber-500 dark:text-amber-400" /> Watchlist
          </h1>
          <p className="text-sm text-zinc-500 mt-0.5">
            {ready ? tickers.length : 0} tracked ·{" "}
            {isLoggedIn ? "synced to your account" : "saved on this device"}
          </p>
        </div>
        <form
          onSubmit={onAdd}
          className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 focus-within:border-sky-500/60 transition-colors"
        >
          <Search size={14} className="text-zinc-500" />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={adding}
            placeholder="Add ticker..."
            className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-28 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={adding}
            className="text-sky-500 dark:text-sky-400 hover:text-sky-600 dark:hover:text-sky-300 disabled:opacity-60 transition-colors"
            aria-label="Add"
          >
            {adding ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          </button>
        </form>
      </div>

      {!ready ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 rounded-xl bg-zinc-100 dark:bg-zinc-900/60 animate-pulse" />
          ))}
        </div>
      ) : tickers.length === 0 ? (
        <Card className="p-10 text-center">
          <Star size={28} className="text-zinc-300 dark:text-zinc-700 mx-auto mb-3" />
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Your watchlist is empty.</p>
          <p className="text-xs text-zinc-400 dark:text-zinc-600 mt-1">
            Add a ticker above or{" "}
            <Link
              href="/screener"
              className="text-sky-600 dark:text-sky-400 hover:text-sky-500 dark:hover:text-sky-300"
            >
              browse the screener
            </Link>
            .
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {tickers.map((t) => {
            const q = quotes[t];
            const sig = signalByTicker[t];
            const up = (q?.change_pct ?? 0) >= 0;
            return (
              <Card
                key={t}
                className="p-3 flex items-center gap-3 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors"
              >
                <Link href={`/signals/${t}`} className="flex items-center gap-3 flex-1 min-w-0">
                  <span className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100 w-16 shrink-0">
                    {t}
                  </span>
                  <div className="flex-1" />
                  <div className="text-right w-24 shrink-0">
                    <p className="font-mono text-sm text-zinc-800 dark:text-zinc-200">
                      {q ? money(q.price) : "—"}
                    </p>
                    {q && (
                      <p
                        className={cn(
                          "font-mono text-xs",
                          up
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-red-600 dark:text-red-400"
                        )}
                      >
                        {signedPct(q.change_pct, 1)}
                      </p>
                    )}
                  </div>
                  <div className="w-20 shrink-0 flex justify-end">
                    {sig ? (
                      <DirectionBadge direction={sig.direction} />
                    ) : (
                      <span className="text-[11px] text-zinc-400 dark:text-zinc-600">—</span>
                    )}
                  </div>
                </Link>
                <button
                  onClick={() => remove(t)}
                  className="text-zinc-400 dark:text-zinc-600 hover:text-red-500 dark:hover:text-red-400 transition-colors p-1 shrink-0"
                  aria-label={`Remove ${t}`}
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
