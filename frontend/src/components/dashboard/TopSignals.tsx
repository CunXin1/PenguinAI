"use client";

import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { Pencil, Plus, X as XIcon, Check, Loader2, RefreshCw } from "lucide-react";
import { useTopSignals } from "@/hooks/useTopSignals";
import { usePinnedSignals } from "@/hooks/usePinnedSignals";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { Sparkline } from "@/components/ui/Sparkline";
import { signedPct, money } from "@/lib/utils";
import { tickers as tickersApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Direction, SignalView } from "@/lib/types";

const FILTERS: ("ALL" | Direction)[] = ["ALL", "LONG", "SHORT", "NEUTRAL"];

export function TopSignals() {
  const pinned = usePinnedSignals();
  const { data } = useTopSignals(pinned.tickers);
  const [filter, setFilter] = useState<"ALL" | Direction>("ALL");
  const [editing, setEditing] = useState(false);

  const list = (data ?? []).filter(
    (s) => filter === "ALL" || s.direction === filter,
  );

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          Top Signals
          <span className="text-[10px] text-zinc-400 font-normal normal-case tracking-normal">
            {pinned.tickers.length}/12
          </span>
        </h2>
        <div className="flex items-center gap-2">
          <div className={cn(
            "transition-opacity",
            editing && !pinned.isFull ? "opacity-100" : "opacity-0 pointer-events-none"
          )}>
            <AddTicker onAdd={pinned.add} has={pinned.has} />
          </div>
          <button
            onClick={() => setEditing((e) => !e)}
            className={cn(
              "p-1 rounded-md transition-colors",
              editing
                ? "bg-sky-500/10 text-sky-500"
                : "text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300",
            )}
            title={editing ? "Done editing" : "Edit tickers"}
          >
            {editing ? <Check size={14} /> : <Pencil size={14} />}
          </button>
          <div className="flex gap-1">
            {FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                  filter === f
                    ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                    : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                }`}
              >
                {f === "ALL" ? "All" : f.charAt(0) + f.slice(1).toLowerCase()}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {list.map((s) => (
          <SignalTile
            key={s.ticker}
            s={s}
            editing={editing}
            onRemove={() => pinned.remove(s.ticker)}
          />
        ))}
      </div>

      {list.length === 0 && !editing && (
        <p className="text-sm text-zinc-400 dark:text-zinc-600 py-8 text-center">
          {pinned.tickers.length === 0
            ? "No pinned tickers — click the pencil to add some."
            : `No ${filter.toLowerCase()} signals right now.`}
        </p>
      )}
    </section>
  );
}

function SignalTile({
  s,
  editing,
  onRemove,
}: {
  s: SignalView;
  editing: boolean;
  onRemove: () => void;
}) {
  const up = (s.change_pct ?? 0) >= 0;
  const inner = (
    <Card className="p-4 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors h-full relative group">
      {editing && (
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onRemove();
          }}
          className="absolute top-1.5 right-1.5 p-1 rounded-md bg-pink-300/20 text-pink-400 dark:text-pink-300/60 grid place-items-center z-10 hover:bg-pink-400/30 hover:text-pink-500 dark:hover:text-pink-400 transition-colors"
          title="Remove"
        >
          <XIcon size={14} />
        </button>
      )}
      <div className="flex items-start gap-2">
        <div className="min-w-0 shrink-0">
          <div className="flex items-center gap-2">
            <span className="font-bold text-zinc-900 dark:text-white font-mono">
              {s.ticker}
            </span>
            <DirectionBadge direction={s.direction} />
          </div>
          {s.name && (
            <p className="text-xs text-zinc-500 mt-0.5 truncate">{s.name}</p>
          )}
        </div>
        <div className="flex-1 min-w-0" />
        <div className="w-1/3 min-w-[48px] max-w-[96px] shrink mr-1">
          {s.spark && (
            <Sparkline data={s.spark} color={up ? "#34d399" : "#f87171"} width={96} height={28} fill />
          )}
        </div>
      </div>

      {s._computing ? (
        <div className="flex items-center gap-2 mt-3 text-zinc-500">
          <RefreshCw size={12} className="animate-spin" />
          <span className="text-xs">Computing signal…</span>
        </div>
      ) : (
        <>
          <div className="flex items-end justify-between mt-3">
            <div>
              {s.price != null && (
                <p className="font-mono text-sm text-zinc-800 dark:text-zinc-200">
                  {money(s.price)}
                </p>
              )}
              {s.change_pct != null && (
                <p
                  className={`text-xs font-mono ${up ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}
                >
                  {signedPct(s.change_pct)}
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </Card>
  );

  if (editing) return <div>{inner}</div>;
  return <Link href={`/signals/${s.ticker}`}>{inner}</Link>;
}

function AddTicker({
  onAdd,
  has,
}: {
  onAdd: (t: string) => Promise<void>;
  has: (t: string) => boolean;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const t = value.trim().toUpperCase();
      if (!t) return;
      if (has(t)) {
        setError("Already pinned");
        return;
      }
      setBusy(true);
      setError("");
      try {
        await tickersApi.get(t);
        await onAdd(t);
        setValue("");
        inputRef.current?.focus();
      } catch {
        setError("Ticker not found");
      } finally {
        setBusy(false);
      }
    },
    [value, onAdd, has],
  );

  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <div className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-1.5 focus-within:border-sky-500/60 transition-colors">
        <Plus size={14} className="text-zinc-400 shrink-0" />
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setError("");
          }}
          placeholder="Add ticker..."
          className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-28"
          autoComplete="off"
        />
        {busy && <Loader2 size={14} className="animate-spin text-zinc-400" />}
      </div>
      {error && (
        <span className="text-xs text-red-500 dark:text-red-400">{error}</span>
      )}
    </form>
  );
}
