"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Search, Sunrise, Moon } from "lucide-react";
import { earnings as earningsApi } from "@/lib/api";
import { MOCK_EARNINGS } from "@/lib/mock";
import { Card } from "@/components/ui/Card";
import { StatTile } from "@/components/ui/StatTile";
import { cn, compact, signedPct } from "@/lib/utils";
import type { EarningsEvent, EarningsSession } from "@/lib/types";

type Tab = "upcoming" | "reported" | "all";
const TABS: { key: Tab; label: string }[] = [
  { key: "upcoming", label: "Upcoming" },
  { key: "reported", label: "Reported" },
  { key: "all", label: "All" },
];

// ── Deterministic date formatting (UTC → no SSR/timezone drift) ───────────────
const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return { weekday: WD[wd], label: `${MO[m - 1]} ${d}`, year: y };
}

const SESSION: Record<EarningsSession, { label: string; cls: string; Icon: typeof Sunrise }> = {
  BMO: { label: "Pre-market", cls: "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/30", Icon: Sunrise },
  AMC: { label: "After-hours", cls: "text-indigo-600 dark:text-indigo-400 bg-indigo-500/10 border-indigo-500/30", Icon: Moon },
  TBD: { label: "TBD", cls: "text-zinc-600 dark:text-zinc-400 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50", Icon: CalendarDays },
};

const isReported = (e: EarningsEvent) => e.eps_actual !== null;

export default function EarningsPage() {
  const [tab, setTab] = useState<Tab>("upcoming");
  const [q, setQ] = useState("");
  const [today, setToday] = useState<string | null>(null);

  // Resolved after mount only — keeps SSR/first paint deterministic.
  useEffect(() => setToday(new Date().toISOString().slice(0, 10)), []);

  const { data } = useQuery<EarningsEvent[]>({
    queryKey: ["earnings"],
    queryFn: async () => {
      try {
        const now = new Date();
        const from = new Date(now.getTime() - 7 * 864e5).toISOString().slice(0, 10);
        const to = new Date(now.getTime() + 30 * 864e5).toISOString().slice(0, 10);
        const list = await earningsApi.calendar(from, to);
        return Array.isArray(list) && list.length ? list : MOCK_EARNINGS;
      } catch {
        return MOCK_EARNINGS;
      }
    },
    initialData: MOCK_EARNINGS,
  });

  const events = data ?? MOCK_EARNINGS;

  const stats = useMemo(() => {
    const reported = events.filter(isReported);
    return {
      upcoming: events.length - reported.length,
      beats: reported.filter((e) => (e.eps_surprise_pct ?? 0) >= 0).length,
      misses: reported.filter((e) => (e.eps_surprise_pct ?? 0) < 0).length,
    };
  }, [events]);

  const groups = useMemo(() => {
    const needle = q.trim().toUpperCase();
    const view = events.filter((e) => {
      if (tab === "upcoming" && isReported(e)) return false;
      if (tab === "reported" && !isReported(e)) return false;
      if (needle && !e.ticker.includes(needle) && !(e.name ?? "").toUpperCase().includes(needle))
        return false;
      return true;
    });

    const byDate = new Map<string, EarningsEvent[]>();
    for (const e of view) (byDate.get(e.report_date) ?? byDate.set(e.report_date, []).get(e.report_date)!).push(e);

    const dates = [...byDate.keys()].sort();
    if (tab === "reported") dates.reverse();
    return dates.map((date) => ({ date, rows: byDate.get(date)! }));
  }, [events, tab, q]);

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <CalendarDays size={20} className="text-sky-500 dark:text-sky-400" /> Earnings Calendar
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          EPS estimates vs. actuals across the signal universe · beats and misses move signals
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <StatTile label="Upcoming" value={stats.upcoming} accent="brand" sub="next 30 days" />
        <StatTile label="Beats" value={stats.beats} accent="up" sub="reported ≥ estimate" />
        <StatTile label="Misses" value={stats.misses} accent="down" sub="reported < estimate" />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                tab === t.key
                  ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                  : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 w-56 focus-within:border-sky-500/60 transition-colors">
          <Search size={14} className="text-zinc-500 shrink-0" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter ticker or name..."
            className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-full"
          />
        </div>
      </div>

      <div className="space-y-4">
        {groups.map(({ date, rows }) => {
          const d = fmtDate(date);
          const isToday = date === today;
          return (
            <div key={date} className="space-y-1.5">
              <div className="flex items-center gap-2 px-1">
                <span className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">{d.weekday}</span>
                <span className="text-sm text-zinc-500">{d.label}</span>
                {isToday && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-sky-500/15 text-sky-600 dark:text-sky-400 border border-sky-500/30">
                    Today
                  </span>
                )}
                <span className="flex-1 h-px bg-zinc-200 dark:bg-zinc-800/70" />
                <span className="text-[11px] text-zinc-400 dark:text-zinc-600">{rows.length}</span>
              </div>
              <Card className="overflow-hidden divide-y divide-zinc-200 dark:divide-zinc-800/70">
                {rows.map((e) => (
                  <EarningsRow key={e.ticker} e={e} />
                ))}
              </Card>
            </div>
          );
        })}

        {groups.length === 0 && (
          <p className="text-center text-sm text-zinc-400 dark:text-zinc-600 py-12">
            No {tab === "all" ? "" : tab} earnings match{q ? ` “${q}”` : ""}.
          </p>
        )}
      </div>

      <p className="text-xs text-zinc-400 dark:text-zinc-600 text-center pt-2">
        Demo calendar — connect the backend for live data from the{" "}
        <span className="font-mono">earnings</span> table.
      </p>
    </div>
  );
}

function EarningsRow({ e }: { e: EarningsEvent }) {
  const reported = isReported(e);
  const sess = SESSION[e.session ?? "TBD"];
  const surprise = e.eps_surprise_pct ?? 0;
  const beat = surprise >= 0;

  return (
    <Link
      href={`/signals/${e.ticker}`}
      className="grid grid-cols-12 gap-2 items-center px-4 py-3 hover:bg-zinc-100 dark:hover:bg-zinc-800/30 transition-colors"
    >
      {/* Ticker + name */}
      <div className="col-span-5 sm:col-span-4 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100">{e.ticker}</span>
          <span
            className={cn("hidden sm:inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium border leading-none", sess.cls)}
            title={sess.label}
          >
            <sess.Icon size={10} /> {e.session ?? "TBD"}
          </span>
        </div>
        {e.name && <p className="text-xs text-zinc-500 truncate mt-0.5">{e.name}</p>}
      </div>

      {/* EPS estimate */}
      <div className="col-span-3 sm:col-span-2 text-right">
        <p className="text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-wide">Est</p>
        <p className="font-mono text-sm text-zinc-700 dark:text-zinc-300">
          {e.eps_estimate != null ? `$${e.eps_estimate.toFixed(2)}` : "—"}
        </p>
      </div>

      {/* EPS actual */}
      <div className="col-span-4 sm:col-span-2 text-right">
        <p className="text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-wide">Actual</p>
        <p className="font-mono text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          {reported ? `$${e.eps_actual!.toFixed(2)}` : "—"}
        </p>
      </div>

      {/* Surprise */}
      <div className="hidden sm:flex col-span-2 justify-end">
        {reported ? (
          <span
            className={cn(
              "px-2 py-0.5 rounded-md text-xs font-mono font-semibold border",
              beat
                ? "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
                : "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30"
            )}
          >
            {signedPct(surprise, 1)}
          </span>
        ) : (
          <span className="text-xs text-zinc-400 dark:text-zinc-600">pending</span>
        )}
      </div>

      {/* Revenue est */}
      <div className="hidden sm:block col-span-2 text-right">
        <p className="text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-wide">Rev est</p>
        <p className="font-mono text-sm text-zinc-600 dark:text-zinc-400">
          {e.revenue_estimate != null ? `$${compact(e.revenue_estimate)}` : "—"}
        </p>
      </div>
    </Link>
  );
}
