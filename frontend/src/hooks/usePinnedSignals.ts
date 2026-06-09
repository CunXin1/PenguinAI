"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { pinnedSignals as api } from "@/lib/api";
import { useAuth } from "./useAuth";

const KEY = "penguinai_pinned_signals";
const MAX = 12;
const DEFAULT = [
  "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "SPY", "QQQ",
];

export function usePinnedSignals() {
  const { isLoggedIn } = useAuth();
  const qc = useQueryClient();

  const server = useQuery<string[]>({
    queryKey: ["pinnedSignals"],
    queryFn: () => api.get(),
    enabled: isLoggedIn,
    staleTime: 30_000,
  });

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

  const tickers = isLoggedIn
    ? (server.data && server.data.length > 0 ? server.data : DEFAULT)
    : local;

  const add = useCallback(
    async (t: string) => {
      const sym = t.toUpperCase();
      if (tickers.includes(sym) || tickers.length >= MAX) return;
      const next = [...tickers, sym];
      if (isLoggedIn) {
        await api.set(next);
        await qc.invalidateQueries({ queryKey: ["pinnedSignals"] });
      } else {
        setLocal(next);
      }
    },
    [isLoggedIn, tickers, qc],
  );

  const remove = useCallback(
    async (t: string) => {
      const sym = t.toUpperCase();
      const next = tickers.filter((x) => x !== sym);
      if (isLoggedIn) {
        await api.set(next);
        await qc.invalidateQueries({ queryKey: ["pinnedSignals"] });
      } else {
        setLocal(next);
      }
    },
    [isLoggedIn, tickers, qc],
  );

  const has = useCallback((t: string) => tickers.includes(t.toUpperCase()), [tickers]);

  return {
    tickers,
    add,
    remove,
    has,
    isFull: tickers.length >= MAX,
    ready: isLoggedIn ? !server.isLoading : localReady,
  };
}
