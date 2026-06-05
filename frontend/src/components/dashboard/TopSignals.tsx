"use client";

import { useState } from "react";
import Link from "next/link";
import { useTopSignals } from "@/hooks/useTopSignals";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { ConfidenceBar } from "@/components/ui/ConfidenceBar";
import { Sparkline } from "@/components/ui/Sparkline";
import { signedPct, money } from "@/lib/utils";
import type { Direction, SignalView } from "@/lib/types";

const FILTERS: ("ALL" | Direction)[] = ["ALL", "LONG", "SHORT", "NEUTRAL"];

const SPARK_COLOR: Record<Direction, string> = {
  LONG: "#34d399",
  SHORT: "#f87171",
  NEUTRAL: "#a1a1aa",
};

export function TopSignals() {
  const { data } = useTopSignals();
  const [filter, setFilter] = useState<"ALL" | Direction>("ALL");
  const list = (data ?? []).filter((s) => filter === "ALL" || s.direction === filter);

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          Top Signals
        </h2>
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                filter === f ? "bg-zinc-800 text-white" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {f === "ALL" ? "All" : f.charAt(0) + f.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
      </div>

      <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {list.map((s) => (
          <SignalTile key={s.ticker} s={s} />
        ))}
      </div>

      {list.length === 0 && (
        <p className="text-sm text-zinc-600 py-8 text-center">No {filter.toLowerCase()} signals right now.</p>
      )}
    </section>
  );
}

function SignalTile({ s }: { s: SignalView }) {
  const up = (s.change_pct ?? 0) >= 0;
  return (
    <Link href={`/signals/${s.ticker}`}>
      <Card className="p-4 hover:border-zinc-700 transition-colors h-full">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-bold text-white font-mono">{s.ticker}</span>
              <DirectionBadge direction={s.direction} />
            </div>
            {s.name && <p className="text-xs text-zinc-500 mt-0.5 truncate">{s.name}</p>}
          </div>
          {s.spark && <Sparkline data={s.spark} color={SPARK_COLOR[s.direction]} />}
        </div>

        <div className="flex items-end justify-between mt-3">
          <div>
            {s.price != null && <p className="font-mono text-sm text-zinc-200">{money(s.price)}</p>}
            {s.change_pct != null && (
              <p className={`text-xs font-mono ${up ? "text-emerald-400" : "text-red-400"}`}>{signedPct(s.change_pct)}</p>
            )}
          </div>
          <div className="text-right">
            <p className="text-[10px] text-zinc-500 uppercase tracking-wide">Conf</p>
            <p className="text-sm font-mono font-bold text-zinc-200">{Math.round(s.confidence * 100)}%</p>
          </div>
        </div>

        <ConfidenceBar value={s.confidence} direction={s.direction} className="mt-2" />
      </Card>
    </Link>
  );
}
