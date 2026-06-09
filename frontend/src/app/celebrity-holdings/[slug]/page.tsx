"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Layers,
} from "lucide-react";
import { celebrityHoldings as api } from "@/lib/api";
import { getCelebrityMeta, getCelebrityColor } from "@/lib/celebrities";
import { CelebrityRing } from "@/components/celebrity/CelebrityRing";
import { Card } from "@/components/ui/Card";
import { cn, compact, timeAgo } from "@/lib/utils";
import type {
  CelebrityHolding,
  CelebritySummary,
  CelebrityTopHolding,
  CelebAction,
} from "@/lib/types";

const ACTION_BADGE: Record<CelebAction, string> = {
  BUY: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  SELL: "text-red-400 bg-red-500/10 border-red-500/30",
  HOLD: "text-zinc-400 bg-zinc-700/40 border-zinc-600/50",
};

export default function CelebrityDetailPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const meta = getCelebrityMeta(slug);
  const color = getCelebrityColor(slug);

  const { data: allStats } = useQuery<CelebritySummary[]>({
    queryKey: ["celebStats"],
    queryFn: () => api.stats(),
  });

  const { data: topHoldings } = useQuery<CelebrityTopHolding[]>({
    queryKey: ["celebTopHoldings", slug],
    queryFn: () => api.topHoldings(slug),
  });

  const { data: recentTrades } = useQuery<CelebrityHolding[]>({
    queryKey: ["celebTrades", slug],
    queryFn: () => api.byCelebrity(slug, 50),
  });

  const stats = useMemo(
    () => allStats?.find((s) => s.celebrity === slug) ?? null,
    [allStats, slug]
  );

  const holdings = topHoldings ?? [];
  const trades = recentTrades ?? [];

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      {/* Back link */}
      <Link
        href="/celebrity-holdings"
        className="inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-white transition-colors"
      >
        <ArrowLeft size={14} /> Smart Money
      </Link>

      {/* Hero */}
      <div className="flex items-center gap-6">
        <CelebrityRing
          buys={stats?.buys ?? 0}
          sells={stats?.sells ?? 0}
          holds={
            (stats?.total_trades ?? 0) -
            (stats?.buys ?? 0) -
            (stats?.sells ?? 0)
          }
          size={140}
          strokeWidth={14}
          initials={meta.avatar}
          gradientClass={color}
          image={meta.image}
        />
        <div>
          <h1 className="text-2xl font-bold text-white">{meta.name}</h1>
          <p className="text-sm text-zinc-400 mt-0.5">{meta.title}</p>
          {stats && (
            <p className="text-xs text-zinc-500 mt-1">
              Last active: {timeAgo(stats.latest_trade)}
            </p>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-3">
        <MiniStat
          icon={<BarChart3 size={14} />}
          label="Trades"
          value={stats?.total_trades ?? 0}
        />
        <MiniStat
          icon={<TrendingUp size={14} />}
          label="Buys"
          value={stats?.buys ?? 0}
          color="text-emerald-400"
        />
        <MiniStat
          icon={<TrendingDown size={14} />}
          label="Sells"
          value={stats?.sells ?? 0}
          color="text-red-400"
        />
        <MiniStat
          icon={<Layers size={14} />}
          label="Tickers"
          value={holdings.length}
        />
      </div>

      {/* Top Holdings */}
      {holdings.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-zinc-300 mb-3">
            Top Holdings
          </h2>
          <Card className="overflow-hidden divide-y divide-zinc-200 dark:divide-zinc-800/70">
            <div className="grid grid-cols-12 gap-2 items-center px-4 py-2 text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-wider font-medium">
              <div className="col-span-4">Ticker</div>
              <div className="col-span-2 text-center">Action</div>
              <div className="col-span-2 text-right">Value</div>
              <div className="col-span-2 text-right">Trades</div>
              <div className="col-span-2 text-right">Last</div>
            </div>
            {holdings.map((h) => (
              <Link
                key={h.ticker}
                href={`/signals/${h.ticker}`}
                className="grid grid-cols-12 gap-2 items-center px-4 py-3 hover:bg-zinc-100 dark:hover:bg-zinc-800/30 transition-colors"
              >
                <div className="col-span-4 min-w-0">
                  <span className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                    {h.ticker}
                  </span>
                  <p className="text-xs text-zinc-500 truncate">
                    {h.ticker_name}
                  </p>
                </div>
                <div className="col-span-2 flex justify-center">
                  <span
                    className={cn(
                      "px-2 py-0.5 rounded-md text-[10px] font-semibold border",
                      ACTION_BADGE[h.latest_action]
                    )}
                  >
                    {h.latest_action}
                  </span>
                </div>
                <div className="col-span-2 text-right">
                  <span className="font-mono text-sm text-zinc-700 dark:text-zinc-300">
                    {h.value_usd != null ? `$${compact(h.value_usd)}` : "—"}
                  </span>
                </div>
                <div className="col-span-2 text-right">
                  <span className="text-sm text-zinc-400">
                    {h.trade_count}
                  </span>
                </div>
                <div className="col-span-2 text-right">
                  <span className="text-xs text-zinc-500">
                    {timeAgo(h.last_activity)}
                  </span>
                </div>
              </Link>
            ))}
          </Card>
        </section>
      )}

      {/* Recent Activity */}
      {trades.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-zinc-300 mb-3">
            Recent Activity
          </h2>
          <Card className="overflow-hidden divide-y divide-zinc-200 dark:divide-zinc-800/70">
            {trades.slice(0, 20).map((t) => (
              <Link
                key={t.id}
                href={`/signals/${t.ticker}`}
                className="flex items-center gap-4 px-4 py-3 hover:bg-zinc-100 dark:hover:bg-zinc-800/30 transition-colors"
              >
                <span
                  className={cn(
                    "px-2 py-0.5 rounded-md text-[10px] font-semibold border shrink-0",
                    ACTION_BADGE[t.action]
                  )}
                >
                  {t.action}
                </span>
                <div className="min-w-0 flex-1">
                  <span className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                    {t.ticker}
                  </span>
                  <span className="text-xs text-zinc-500 ml-2">
                    {t.ticker_name}
                  </span>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-mono text-sm text-zinc-700 dark:text-zinc-300">
                    {t.shares != null ? `${compact(t.shares)} shares` : ""}
                    {t.value_usd != null ? ` · $${compact(t.value_usd)}` : ""}
                  </p>
                  <p className="text-xs text-zinc-500 mt-0.5">
                    {timeAgo(t.reported_at)}
                    <span className="text-zinc-600 ml-2">
                      {t.source_type === "13F" ? "13F Filing" : "Disclosure"}
                    </span>
                  </p>
                </div>
              </Link>
            ))}
          </Card>
        </section>
      )}
    </div>
  );
}

function MiniStat({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  color?: string;
}) {
  return (
    <Card className="px-4 py-3">
      <div className="flex items-center gap-2 text-zinc-500 mb-1">
        {icon}
        <span className="text-[10px] uppercase tracking-wider font-medium">
          {label}
        </span>
      </div>
      <p className={cn("text-xl font-bold text-zinc-900 dark:text-white", color)}>
        {value}
      </p>
    </Card>
  );
}
