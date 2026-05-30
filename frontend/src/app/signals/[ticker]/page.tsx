"use client";

import { useEffect, useState } from "react";
import { use } from "react";
import { signals as signalApi, marketData } from "@/lib/api";
import { SignalCard } from "@/components/signals/SignalCard";
import type { Signal, Candle } from "@/lib/types";

interface Props {
  params: Promise<{ ticker: string }>;
}

export default function SignalDetailPage({ params }: Props) {
  const { ticker } = use(params);
  const upperTicker = ticker.toUpperCase();

  const [signal, setSignal] = useState<Signal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchWithRetry = async (retries = 3) => {
      try {
        const data = await signalApi.getByTicker(upperTicker);
        setSignal(data);
        setLoading(false);
      } catch (err: any) {
        if (err.status === 202 && retries > 0) {
          // Signal is being computed — poll after 5s (real animation)
          setTimeout(() => fetchWithRetry(retries - 1), 5000);
        } else {
          setError(err.message ?? "Failed to load signal");
          setLoading(false);
        }
      }
    };

    fetchWithRetry();
  }, [upperTicker]);

  return (
    <main className="min-h-screen p-6 max-w-2xl mx-auto space-y-6">
      {/* Back navigation */}
      <a href="/" className="text-sm text-zinc-500 hover:text-zinc-300 transition-colors flex items-center gap-1">
        ← Back to Dashboard
      </a>

      <h1 className="text-3xl font-bold font-mono text-white">{upperTicker}</h1>

      {loading && (
        <div className="space-y-3">
          <div className="h-4 bg-zinc-800 rounded animate-pulse w-1/2" />
          <div className="h-48 bg-zinc-800/60 rounded-xl animate-pulse" />
          <p className="text-sm text-zinc-500 text-center">Computing signal...</p>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {signal && !loading && <SignalCard signal={signal} />}
    </main>
  );
}
