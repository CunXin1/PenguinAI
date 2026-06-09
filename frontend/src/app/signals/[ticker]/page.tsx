"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, ArrowRight, Star, Loader2, Newspaper, ExternalLink,
  CalendarDays, Sunrise, Moon, TrendingUp, TrendingDown,
} from "lucide-react";
import { signals as signalApi, news, earnings as earningsApi } from "@/lib/api";
import { PriceChart } from "@/components/charts/PriceChart";
import { SignalCard } from "@/components/signals/SignalCard";
import { UnknownSymbol } from "@/components/signals/UnknownSymbol";
import { Card } from "@/components/ui/Card";
import { mockSignalDetail } from "@/lib/mock";
import { cn, compact, signedPct, timeAgoUnix } from "@/lib/utils";
import type { ApiError, EarningsEvent, EarningsSession, NewsApiArticle, Signal } from "@/lib/types";

interface Props {
  params: Promise<{ ticker: string }>;
}

const WL_KEY = "penguinai_watchlist";
const MAX_POLLS = 10; // ~50s of polling a cold ticker before giving up
const POLL_MS = 5000;

type View = "loading" | "live" | "demo" | "computing" | "unknown";

export default function SignalDetailPage({ params }: Props) {
  const { ticker } = use(params);
  const T = ticker.toUpperCase();

  const [signal, setSignal] = useState<Signal | null>(null);
  const [view, setView] = useState<View>("loading");
  const [reason, setReason] = useState<"not_in_universe" | "delisted">("not_in_universe");
  const [watched, setWatched] = useState(false);

  const { data: tickerNews } = useQuery({
    queryKey: ["tickerNews", T],
    queryFn: () => news.byTicker(T, 7),
    staleTime: 5 * 60 * 1000,
    enabled: view !== "unknown",
  });

  const { data: tickerEarnings } = useQuery<EarningsEvent[]>({
    queryKey: ["tickerEarnings", T],
    queryFn: () => earningsApi.byTicker(T),
    staleTime: 10 * 60 * 1000,
    enabled: view !== "unknown",
  });

  useEffect(() => {
    let active = true;
    let polls = 0;
    let timer: ReturnType<typeof setTimeout>;

    const load = async (poll = false) => {
      try {
        const data = await signalApi.getByTicker(T, poll);
        if (!active) return;
        setSignal(data);
        setView("live");
      } catch (e) {
        if (!active) return;
        const err = e as ApiError;
        if (err.status === 404) {
          // Symbol isn't in our universe — show the not-found view, no fake data.
          setReason(err.data?.reason === "delisted" ? "delisted" : "not_in_universe");
          setView("unknown");
        } else if (err.status === 202) {
          // Covered cold ticker computing on demand — poll (without re-triggering).
          setView("computing");
          if (polls < MAX_POLLS) {
            polls += 1;
            timer = setTimeout(() => load(true), POLL_MS);
          } else {
            setSignal(mockSignalDetail(T));
            setView("demo");
          }
        } else {
          // Network / auth / server error — keep the page alive with demo data.
          setSignal(mockSignalDetail(T));
          setView("demo");
        }
      }
    };

    setSignal(null);
    setView("loading");
    load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [T]);

  const addToWatchlist = () => {
    try {
      const cur = JSON.parse(localStorage.getItem(WL_KEY) || "[]");
      const arr = Array.isArray(cur) ? cur : [];
      if (!arr.includes(T)) localStorage.setItem(WL_KEY, JSON.stringify([T, ...arr]));
      setWatched(true);
    } catch {
      setWatched(true);
    }
  };

  // Unknown / delisted symbol → dedicated view, rendered in place (URL stays /signals/T).
  if (view === "unknown") {
    return <UnknownSymbol symbol={T} reason={reason} />;
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <Link
        href="/"
        className="text-sm text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 flex items-center gap-1 w-fit transition-colors"
      >
        <ArrowLeft size={14} /> Dashboard
      </Link>

      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-3xl font-bold font-mono text-zinc-900 dark:text-white">{T}</h1>
        <button
          onClick={addToWatchlist}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors"
        >
          <Star
            size={14}
            className={
              watched ? "text-amber-500 dark:text-amber-400 fill-amber-500 dark:fill-amber-400" : ""
            }
          />
          {watched ? "Watching" : "Watch"}
        </button>
      </div>

      <PriceChart ticker={T} defaultRange="1W" height={360} />

      {view === "computing" && !signal ? (
        <Card className="h-56 grid place-items-center text-center">
          <div className="flex flex-col items-center gap-3 text-zinc-500 dark:text-zinc-400">
            <Loader2 size={22} className="animate-spin text-sky-500" />
            <p className="text-sm">
              Generating a fresh signal for{" "}
              <span className="font-mono font-semibold text-zinc-700 dark:text-zinc-200">{T}</span>…
            </p>
            <p className="text-xs text-zinc-400 dark:text-zinc-600">This usually takes a few seconds.</p>
          </div>
        </Card>
      ) : !signal ? (
        <div className="h-56 rounded-xl bg-zinc-100 dark:bg-zinc-900/60 animate-pulse" />
      ) : (
        <SignalCard signal={signal} />
      )}

      {(view === "live" || view === "demo") && tickerNews && tickerNews.length > 0 && (
        <Card className="p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
              <Newspaper size={15} className="text-sky-500" />
              Latest News for {T}
            </h3>
            <Link
              href="/news"
              className="text-xs text-zinc-500 hover:text-sky-500 flex items-center gap-1 transition-colors"
            >
              View all <ArrowRight size={12} />
            </Link>
          </div>
          <div className="space-y-3">
            {tickerNews.slice(0, 5).map((article: NewsApiArticle) => (
              <div key={article.id} className="flex items-start gap-2.5">
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-zinc-500" />
                <div className="min-w-0">
                  {article.url ? (
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm font-medium text-zinc-800 dark:text-zinc-200 hover:text-sky-500 dark:hover:text-sky-400 transition-colors inline-flex items-center gap-1"
                    >
                      <span className="line-clamp-1">{article.headline}</span>
                      <ExternalLink size={11} className="shrink-0 text-zinc-400 dark:text-zinc-600" />
                    </a>
                  ) : (
                    <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200 line-clamp-1">
                      {article.headline}
                    </p>
                  )}
                  <p className="text-xs text-zinc-400 dark:text-zinc-600 mt-0.5">
                    {article.source} · {timeAgoUnix(article.datetime)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {(view === "live" || view === "demo") && tickerEarnings && tickerEarnings.length > 0 && (
        <EarningsSection ticker={T} earnings={tickerEarnings} />
      )}

      <p className="text-xs text-zinc-400 dark:text-zinc-600 text-center">
        {view === "live"
          ? "Live signal from the API."
          : view === "computing"
            ? "Waiting on live ML output…"
            : "Demo signal — connect the backend for live ML output."}
      </p>
    </div>
  );
}

/* ── Earnings section ─────────────────────────────────────────────── */

const SESSION_STYLE: Record<EarningsSession, { label: string; cls: string; Icon: typeof Sunrise }> = {
  BMO: { label: "Pre-market", cls: "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/30", Icon: Sunrise },
  AMC: { label: "After-hours", cls: "text-indigo-600 dark:text-indigo-400 bg-indigo-500/10 border-indigo-500/30", Icon: Moon },
  TBD: { label: "TBD", cls: "text-zinc-500 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50", Icon: CalendarDays },
};

function SessionBadge({ session, small }: { session: EarningsSession; small?: boolean }) {
  const s = SESSION_STYLE[session];
  const Icon = s.Icon;
  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 font-medium border leading-none",
      small ? "px-1 py-0.5 rounded text-[9px]" : "px-1.5 py-0.5 rounded-full text-[10px] gap-1",
      s.cls,
    )}>
      <Icon size={small ? 9 : 10} /> {session}
    </span>
  );
}

function EarningsSection({ ticker, earnings }: { ticker: string; earnings: EarningsEvent[] }) {
  const reported = earnings.filter((e) => e.eps_actual !== null);
  const upcoming = earnings.filter((e) => e.eps_actual === null);
  const next = upcoming.length > 0 ? upcoming[upcoming.length - 1] : null;

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
          <CalendarDays size={15} className="text-sky-500" />
          Earnings for {ticker}
        </h3>
        <Link
          href="/earnings"
          className="text-xs text-zinc-500 hover:text-sky-500 flex items-center gap-1 transition-colors"
        >
          Calendar <ArrowRight size={12} />
        </Link>
      </div>

      {/* Next upcoming */}
      {next && (
        <div className="mb-3 px-3 py-2.5 rounded-lg bg-sky-500/5 border border-sky-500/20">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-sky-600 dark:text-sky-400 uppercase tracking-wider">
                Next Report
              </span>
              <span className="font-mono text-sm text-zinc-800 dark:text-zinc-200">
                {next.report_date}
              </span>
              {next.session && <SessionBadge session={next.session} />}
            </div>
            {next.eps_estimate != null && (
              <span className="text-xs text-zinc-500">
                EPS est <span className="font-mono font-semibold text-zinc-700 dark:text-zinc-300">${next.eps_estimate.toFixed(2)}</span>
              </span>
            )}
          </div>
          {next.revenue_estimate != null && (
            <p className="text-xs text-zinc-500 mt-1">
              Revenue est <span className="font-mono">${compact(next.revenue_estimate)}</span>
            </p>
          )}
        </div>
      )}

      {/* Recent reported */}
      {reported.length > 0 && (
        <div className="rounded-lg overflow-hidden border border-zinc-200 dark:border-zinc-800">
          <div className="grid grid-cols-12 gap-1 px-3 py-1.5 bg-zinc-100 dark:bg-zinc-800/60 text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
            <div className="col-span-3">Date</div>
            <div className="col-span-2 text-right">EPS Est</div>
            <div className="col-span-2 text-right">EPS Act</div>
            <div className="col-span-2 text-right">Surprise</div>
            <div className="col-span-3 text-right">Revenue</div>
          </div>
          {reported.slice(0, 4).map((e) => {
            const s = e.eps_surprise_pct ?? 0;
            const beat = s >= 0;
            return (
              <div
                key={e.report_date}
                className="grid grid-cols-12 gap-1 px-3 py-2 border-t border-zinc-100 dark:border-zinc-800/40 text-xs"
              >
                <div className="col-span-3 font-mono text-zinc-600 dark:text-zinc-400 flex items-center gap-1.5">
                  {e.report_date}
                  {e.session && <span className="hidden sm:inline-flex"><SessionBadge session={e.session} small /></span>}
                </div>
                <div className="col-span-2 text-right font-mono text-zinc-500">
                  {e.eps_estimate != null ? `$${e.eps_estimate.toFixed(2)}` : "—"}
                </div>
                <div className="col-span-2 text-right font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                  ${e.eps_actual!.toFixed(2)}
                </div>
                <div className="col-span-2 text-right">
                  <span className={cn(
                    "inline-flex items-center gap-0.5 font-mono font-semibold",
                    beat ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400",
                  )}>
                    {beat ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                    {signedPct(s, 1)}
                  </span>
                </div>
                <div className="col-span-3 text-right font-mono text-zinc-500">
                  {e.revenue_actual != null
                    ? `$${compact(e.revenue_actual)}`
                    : e.revenue_estimate != null
                      ? `~$${compact(e.revenue_estimate)}`
                      : "—"}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {reported.length === 0 && !next && (
        <p className="text-xs text-zinc-500 text-center py-4">No earnings data available</p>
      )}
    </Card>
  );
}
