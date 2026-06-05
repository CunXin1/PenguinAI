"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { watchlist as wlApi } from "@/lib/api";
import { useAuth } from "./useAuth";
import type { SignalListItem, WatchlistItem } from "@/lib/types";

const KEY = "penguinai_watchlist";
const DEFAULT = ["NVDA", "TSLA", "AAPL", "PLTR"];

/**
 * Unified watchlist: the backend (`/watchlist`, cross-device) when signed in,
 * localStorage otherwise. Same API surface for both so callers don't branch.
 */
export function useWatchlist() {
  const { isLoggedIn } = useAuth();
  const qc = useQueryClient();

  // ── Signed-in: server-backed ──────────────────────────────────────────────
  const server = useQuery<WatchlistItem[]>({
    queryKey: ["watchlist"],
    queryFn: () => wlApi.get(),
    enabled: isLoggedIn,
    staleTime: 30_000,
  });

  // ── Guest: localStorage ───────────────────────────────────────────────────
  const [local, setLocal] = useState<string[]>([]);
  const [localReady, setLocalReady] = useState(false);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) || "null");
      setLocal(Array.isArray(saved) ? saved : DEFAULT);
    } catch {
      setLocal(DEFAULT);
    }
    setLocalReady(true);
  }, []);
  useEffect(() => {
    if (localReady && !isLoggedIn) localStorage.setItem(KEY, JSON.stringify(local));
  }, [local, localReady, isLoggedIn]);

  const tickers = isLoggedIn ? (server.data ?? []).map((w) => w.ticker) : local;
  const signalByTicker: Record<string, SignalListItem | null> = isLoggedIn
    ? Object.fromEntries((server.data ?? []).map((w) => [w.ticker, w.signal]))
    : {};

  const add = useCallback(
    async (t: string) => {
      const sym = t.toUpperCase();
      if (isLoggedIn) {
        await wlApi.add(sym);
        await qc.invalidateQueries({ queryKey: ["watchlist"] });
      } else {
        setLocal((prev) => (prev.includes(sym) ? prev : [sym, ...prev]));
      }
    },
    [isLoggedIn, qc]
  );

  const remove = useCallback(
    async (t: string) => {
      const sym = t.toUpperCase();
      if (isLoggedIn) {
        await wlApi.remove(sym);
        await qc.invalidateQueries({ queryKey: ["watchlist"] });
      } else {
        setLocal((prev) => prev.filter((x) => x !== sym));
      }
    },
    [isLoggedIn, qc]
  );

  const has = useCallback((t: string) => tickers.includes(t.toUpperCase()), [tickers]);

  return {
    tickers,
    signalByTicker,
    add,
    remove,
    has,
    isLoggedIn,
    ready: isLoggedIn ? !server.isLoading : localReady,
  };
}
