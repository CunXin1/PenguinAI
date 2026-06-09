"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  Search,
  Sunrise,
  Moon,
  ChevronRight,
  RefreshCw,
  AlertCircle,
  BarChart3,
  ExternalLink,
} from "lucide-react";
import { earnings as earningsApi } from "@/lib/api";
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

const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MO = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
function fmtDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return { weekday: WD[wd], label: `${MO[m - 1]} ${d}`, year: y };
}

const SESSION: Record<
  EarningsSession,
  { label: string; cls: string; Icon: typeof Sunrise }
> = {
  BMO: {
    label: "Pre-market",
    cls: "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/30",
    Icon: Sunrise,
  },
  AMC: {
    label: "After-hours",
    cls: "text-indigo-600 dark:text-indigo-400 bg-indigo-500/10 border-indigo-500/30",
    Icon: Moon,
  },
  TBD: {
    label: "TBD",
    cls: "text-zinc-600 dark:text-zinc-400 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50",
    Icon: CalendarDays,
  },
};

const isReported = (e: EarningsEvent) => e.eps_actual !== null;

/* ── Loading skeleton ───────────────────────────────────────────── */
function Skeleton() {
  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <div>
        <div className="h-6 w-48 rounded bg-zinc-200 dark:bg-zinc-800 animate-pulse" />
        <div className="h-4 w-72 rounded bg-zinc-100 dark:bg-zinc-800/60 animate-pulse mt-2" />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-20 rounded-xl bg-zinc-100 dark:bg-zinc-900/60 animate-pulse"
          />
        ))}
      </div>
      <div className="space-y-4">
        {[0, 1, 2].map((g) => (
          <div key={g} className="space-y-1.5">
            <div className="h-4 w-32 rounded bg-zinc-200 dark:bg-zinc-800 animate-pulse" />
            <Card className="divide-y divide-zinc-200 dark:divide-zinc-800/70">
              {[0, 1, 2].map((r) => (
                <div
                  key={r}
                  className="h-14 animate-pulse bg-zinc-50 dark:bg-zinc-800/20"
                />
              ))}
            </Card>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Error state ────────────────────────────────────────────────── */
function ErrorBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <Card className="py-16 flex flex-col items-center gap-4 text-center">
        <AlertCircle size={32} className="text-red-500" />
        <div>
          <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
            Failed to load earnings data
          </p>
          <p className="text-xs text-zinc-500 mt-1">
            The backend may be offline or the earnings table is empty.
          </p>
        </div>
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium
                     bg-sky-500/15 text-sky-600 dark:text-sky-400 border border-sky-500/30
                     hover:bg-sky-500/25 transition-colors"
        >
          <RefreshCw size={12} /> Retry
        </button>
      </Card>
    </div>
  );
}

/* ── Empty state ────────────────────────────────────────────────── */
function EmptyBanner() {
  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <CalendarDays size={20} className="text-sky-500 dark:text-sky-400" />
          Earnings Calendar
        </h1>
      </div>
      <Card className="py-16 flex flex-col items-center gap-4 text-center">
        <BarChart3 size={32} className="text-zinc-400 dark:text-zinc-600" />
        <div>
          <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
            No earnings data yet
          </p>
          <p className="text-xs text-zinc-500 mt-1 max-w-sm">
            Run{" "}
            <code className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 font-mono text-[11px]">
              make fetch-earnings
            </code>{" "}
            to pull the Finnhub earnings calendar into the database.
          </p>
        </div>
      </Card>
    </div>
  );
}

/* ── EPS sparkline ──────────────────────────────────────────────── */
function EpsSparkline({ history }: { history: EarningsEvent[] }) {
  const pts = history.filter(isReported).slice(0, 8).reverse();
  if (pts.length < 2) return null;

  const vals = pts.map((e) => e.eps_actual!);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const range = hi - lo || 1;
  const W = 100;
  const H = 28;
  const pad = 3;

  const line = vals
    .map((v, i) => {
      const x = pad + (i / (vals.length - 1)) * (W - 2 * pad);
      const y = H - pad - ((v - lo) / range) * (H - 2 * pad);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const lastY = H - pad - ((vals[vals.length - 1] - lo) / range) * (H - 2 * pad);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-[100px] h-7 shrink-0">
      <polyline
        points={line}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-sky-500"
      />
      <circle
        cx={(W - pad).toFixed(1)}
        cy={lastY.toFixed(1)}
        r="2"
        className="fill-sky-500"
      />
    </svg>
  );
}

/* ── Per-ticker expanded detail ─────────────────────────────────── */
function EarningsDetail({
  ticker,
  current,
}: {
  ticker: string;
  current: EarningsEvent;
}) {
  const { data, isLoading } = useQuery<EarningsEvent[]>({
    queryKey: ["earnings-history", ticker],
    queryFn: () => earningsApi.byTicker(ticker),
  });

  const history = data ?? [];

  return (
    <div className="px-4 pb-4 pt-2 bg-zinc-50 dark:bg-zinc-900/40 border-t border-zinc-100 dark:border-zinc-800/50">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <BarChart3 size={13} className="text-sky-500" />
            <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
              {ticker} Earnings History
            </span>
          </div>
          {!isLoading && <EpsSparkline history={history} />}
        </div>
        <Link
          href={`/signals/${ticker}`}
          className="flex items-center gap-1 text-[11px] text-sky-600 dark:text-sky-400 hover:underline"
          onClick={(ev) => ev.stopPropagation()}
        >
          Signal <ExternalLink size={10} />
        </Link>
      </div>

      {isLoading ? (
        <div className="space-y-1.5">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-7 rounded bg-zinc-200 dark:bg-zinc-800 animate-pulse"
            />
          ))}
        </div>
      ) : history.length === 0 ? (
        <p className="text-xs text-zinc-500 py-4 text-center">
          No historical data available
        </p>
      ) : (
        <div className="rounded-lg overflow-hidden border border-zinc-200 dark:border-zinc-800">
          <div className="grid grid-cols-12 gap-1 px-3 py-1.5 bg-zinc-100 dark:bg-zinc-800/60 text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
            <div className="col-span-2">Date</div>
            <div className="col-span-2 text-right">EPS Est</div>
            <div className="col-span-2 text-right">EPS Act</div>
            <div className="col-span-2 text-right">Surprise</div>
            <div className="col-span-2 text-right">Rev Est</div>
            <div className="col-span-2 text-right">Rev Act</div>
          </div>
          {history.slice(0, 8).map((h) => {
            const r = isReported(h);
            const s = h.eps_surprise_pct ?? 0;
            const b = s >= 0;
            return (
              <div
                key={h.report_date}
                className="grid grid-cols-12 gap-1 px-3 py-1.5 border-t border-zinc-100 dark:border-zinc-800/40 text-xs"
              >
                <div className="col-span-2 font-mono text-zinc-500">
                  {h.report_date.slice(0, 7)}
                </div>
                <div className="col-span-2 text-right font-mono text-zinc-600 dark:text-zinc-400">
                  {h.eps_estimate != null ? `$${h.eps_estimate.toFixed(2)}` : "—"}
                </div>
                <div className="col-span-2 text-right font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                  {r ? `$${h.eps_actual!.toFixed(2)}` : "—"}
                </div>
                <div className="col-span-2 text-right">
                  {r ? (
                    <span
                      className={cn(
                        "font-mono font-semibold",
                        b
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-red-600 dark:text-red-400"
                      )}
                    >
                      {signedPct(s, 1)}
                    </span>
                  ) : (
                    <span className="text-zinc-400">{"—"}</span>
                  )}
                </div>
                <div className="col-span-2 text-right font-mono text-zinc-600 dark:text-zinc-400">
                  {h.revenue_estimate != null
                    ? `$${compact(h.revenue_estimate)}`
                    : "—"}
                </div>
                <div className="col-span-2 text-right font-mono text-zinc-600 dark:text-zinc-400">
                  {h.revenue_actual != null
                    ? `$${compact(h.revenue_actual)}`
                    : "—"}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {current.guidance_text && (
        <p className="mt-3 text-xs text-zinc-500 italic leading-relaxed">
          &ldquo;{current.guidance_text}&rdquo;
        </p>
      )}
    </div>
  );
}

/* ── Single earnings row ────────────────────────────────────────── */
function EarningsRow({
  e,
  isOpen,
  onToggle,
}: {
  e: EarningsEvent;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const reported = isReported(e);
  const sess = SESSION[e.session ?? "TBD"];
  const surprise = e.eps_surprise_pct ?? 0;
  const beat = surprise >= 0;

  return (
    <div>
      <div
        onClick={onToggle}
        className="grid grid-cols-12 gap-2 items-center px-4 py-3
                   hover:bg-zinc-50 dark:hover:bg-zinc-800/30 transition-colors cursor-pointer"
      >
        {/* ticker + name */}
        <div className="col-span-5 sm:col-span-4 min-w-0 flex items-center gap-2">
          <ChevronRight
            size={14}
            className={cn(
              "text-zinc-400 dark:text-zinc-600 shrink-0 transition-transform duration-150",
              isOpen && "rotate-90"
            )}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                {e.ticker}
              </span>
              <span
                className={cn(
                  "hidden sm:inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium border leading-none",
                  sess.cls
                )}
                title={sess.label}
              >
                <sess.Icon size={10} /> {e.session ?? "TBD"}
              </span>
            </div>
            {e.name && (
              <p className="text-xs text-zinc-500 truncate mt-0.5">{e.name}</p>
            )}
          </div>
        </div>

        {/* EPS estimate */}
        <div className="col-span-3 sm:col-span-2 text-right">
          <p className="text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-wide">
            Est
          </p>
          <p className="font-mono text-sm text-zinc-700 dark:text-zinc-300">
            {e.eps_estimate != null ? `$${e.eps_estimate.toFixed(2)}` : "—"}
          </p>
        </div>

        {/* EPS actual */}
        <div className="col-span-4 sm:col-span-2 text-right">
          <p className="text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-wide">
            Actual
          </p>
          <p className="font-mono text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            {reported ? `$${e.eps_actual!.toFixed(2)}` : "—"}
          </p>
        </div>

        {/* surprise badge */}
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
            <span className="text-xs text-zinc-400 dark:text-zinc-600">
              pending
            </span>
          )}
        </div>

        {/* revenue */}
        <div className="hidden sm:block col-span-2 text-right">
          <p className="text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-wide">
            {reported && e.revenue_actual != null ? "Revenue" : "Rev Est"}
          </p>
          <p className="font-mono text-sm text-zinc-600 dark:text-zinc-400">
            {reported && e.revenue_actual != null
              ? `$${compact(e.revenue_actual)}`
              : e.revenue_estimate != null
                ? `$${compact(e.revenue_estimate)}`
                : "—"}
          </p>
        </div>
      </div>

      {isOpen && <EarningsDetail ticker={e.ticker} current={e} />}
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────────── */
export default function EarningsPage() {
  const [tab, setTab] = useState<Tab>("upcoming");
  const [q, setQ] = useState("");
  const [today, setToday] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => setToday(new Date().toISOString().slice(0, 10)), []);

  const { data, isLoading, isError, refetch } = useQuery<EarningsEvent[]>({
    queryKey: ["earnings-calendar"],
    queryFn: async () => {
      const now = new Date();
      const from = new Date(now.getTime() - 7 * 864e5).toISOString().slice(0, 10);
      const to = new Date(now.getTime() + 30 * 864e5).toISOString().slice(0, 10);
      return earningsApi.calendar(from, to);
    },
  });

  const events = useMemo(() => data ?? [], [data]);

  const stats = useMemo(() => {
    const reported = events.filter(isReported);
    const beats = reported.filter((e) => (e.eps_surprise_pct ?? 0) > 0);
    const misses = reported.filter((e) => (e.eps_surprise_pct ?? 0) < 0);
    const avgSurprise = reported.length
      ? reported.reduce((s, e) => s + (e.eps_surprise_pct ?? 0), 0) / reported.length
      : 0;
    return {
      upcoming: events.length - reported.length,
      beats: beats.length,
      misses: misses.length,
      avgSurprise,
    };
  }, [events]);

  const groups = useMemo(() => {
    const needle = q.trim().toUpperCase();
    const view = events.filter((e) => {
      if (tab === "upcoming" && isReported(e)) return false;
      if (tab === "reported" && !isReported(e)) return false;
      if (
        needle &&
        !e.ticker.includes(needle) &&
        !(e.name ?? "").toUpperCase().includes(needle)
      )
        return false;
      return true;
    });

    const byDate = new Map<string, EarningsEvent[]>();
    for (const e of view)
      (byDate.get(e.report_date) ?? byDate.set(e.report_date, []).get(e.report_date)!).push(e);

    const dates = [...byDate.keys()].sort();
    if (tab === "reported") dates.reverse();
    return dates.map((d) => ({ date: d, rows: byDate.get(d)! }));
  }, [events, tab, q]);

  if (isLoading) return <Skeleton />;
  if (isError) return <ErrorBanner onRetry={() => refetch()} />;
  if (events.length === 0) return <EmptyBanner />;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <CalendarDays size={20} className="text-sky-500 dark:text-sky-400" />
          Earnings Calendar
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          EPS estimates vs. actuals across the signal universe
        </p>
      </div>

      {/* stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatTile label="Upcoming" value={stats.upcoming} accent="brand" sub="next 30 days" />
        <StatTile label="Beats" value={stats.beats} accent="up" sub="EPS > estimate" />
        <StatTile label="Misses" value={stats.misses} accent="down" sub="EPS < estimate" />
        <StatTile
          label="Avg Surprise"
          value={signedPct(stats.avgSurprise, 1)}
          accent={stats.avgSurprise >= 0 ? "up" : "down"}
          sub="reported average"
        />
      </div>

      {/* tabs + search */}
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
            onChange={(ev) => setQ(ev.target.value)}
            placeholder="Filter ticker or name..."
            className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-full"
          />
        </div>
      </div>

      {/* calendar groups */}
      <div className="space-y-4">
        {groups.map(({ date, rows }) => {
          const d = fmtDate(date);
          const isToday = date === today;
          return (
            <div key={date} className="space-y-1.5">
              <div className="flex items-center gap-2 px-1">
                <span className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                  {d.weekday}
                </span>
                <span className="text-sm text-zinc-500">{d.label}</span>
                {isToday && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-sky-500/15 text-sky-600 dark:text-sky-400 border border-sky-500/30">
                    Today
                  </span>
                )}
                <span className="flex-1 h-px bg-zinc-200 dark:bg-zinc-800/70" />
                <span className="text-[11px] text-zinc-400 dark:text-zinc-600">
                  {rows.length}
                </span>
              </div>
              <Card className="overflow-hidden divide-y divide-zinc-200 dark:divide-zinc-800/70">
                {rows.map((e) => {
                  const rowKey = `${e.ticker}:${date}`;
                  return (
                    <EarningsRow
                      key={rowKey}
                      e={e}
                      isOpen={expanded === rowKey}
                      onToggle={() =>
                        setExpanded(expanded === rowKey ? null : rowKey)
                      }
                    />
                  );
                })}
              </Card>
            </div>
          );
        })}

        {groups.length === 0 && (
          <p className="text-center text-sm text-zinc-400 dark:text-zinc-600 py-12">
            No {tab === "all" ? "" : tab} earnings match
            {q ? ` "${q}"` : ""}.
          </p>
        )}
      </div>

      <p className="text-xs text-zinc-400 dark:text-zinc-600 text-center pt-2">
        {events.length} earnings events &middot; Finnhub data &middot; refreshed 3&times;/day
      </p>
    </div>
  );
}
