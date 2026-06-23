"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft, ArrowRight, Star, Loader2, Newspaper, ExternalLink,
  CalendarDays, Sunrise, Moon, TrendingUp, TrendingDown, Crown, Clock, Lock,
  AlertTriangle, RotateCw,
} from "lucide-react";
import {
  signals as signalApi,
  news,
  earnings as earningsApi,
  tickers as tickerApi,
  celebrityHoldings as celebApi,
} from "@/lib/api";
import { PriceChart } from "@/components/charts/PriceChart";
import { SignalCard } from "@/components/signals/SignalCard";
import { KeyStats } from "@/components/signals/KeyStats";
import { UnknownSymbol } from "@/components/signals/UnknownSymbol";
import { Card } from "@/components/ui/Card";
import { useWatchlist } from "@/hooks/useWatchlist";
import { getCelebrityMeta, getCelebrityColor } from "@/lib/celebrities";
import { cn, compact, signedPct, timeAgo, timeAgoUnix } from "@/lib/utils";
import type {
  ApiError, CelebAction, CelebrityHolding, EarningsEvent, EarningsSession,
  NewsApiArticle, Signal, Ticker,
} from "@/lib/types";

interface Props {
  params: Promise<{ ticker: string }>;
}

function NewsSentimentBar({ articles }: { articles: NewsApiArticle[] }) {
  const counts = { positive: 0, negative: 0, neutral: 0 };
  for (const a of articles) {
    const s = a.sentiment ?? "neutral";
    if (s in counts) counts[s as keyof typeof counts]++;
    else counts.neutral++;
  }
  const total = articles.length;
  if (total === 0) return null;

  const net = counts.positive >= counts.negative ? "Bullish" : "Bearish";
  const netCls = counts.positive >= counts.negative
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-red-600 dark:text-red-400";

  return (
    <div className="mb-3 px-3 py-2.5 rounded-lg bg-zinc-100 dark:bg-zinc-800/40">
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">News sentiment</p>
        <span className={cn("text-xs font-semibold", netCls)}>{net} bias</span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden flex bg-zinc-200 dark:bg-zinc-700">
        <div className="bg-emerald-500" style={{ width: `${(counts.positive / total) * 100}%` }} />
        <div className="bg-zinc-400 dark:bg-zinc-500" style={{ width: `${(counts.neutral / total) * 100}%` }} />
        <div className="bg-red-500" style={{ width: `${(counts.negative / total) * 100}%` }} />
      </div>
      <div className="flex gap-3 mt-1.5 text-[10px] text-zinc-500">
        <span><span className="text-emerald-600 dark:text-emerald-400 font-mono">{counts.positive}</span> bullish</span>
        <span><span className="text-zinc-700 dark:text-zinc-300 font-mono">{counts.neutral}</span> neutral</span>
        <span><span className="text-red-600 dark:text-red-400 font-mono">{counts.negative}</span> bearish</span>
      </div>
    </div>
  );
}

const MAX_POLLS = 10; // ~50s of polling a cold ticker before giving up
const POLL_MS = 5000;

type View = "loading" | "live" | "computing" | "locked" | "unknown" | "error";

// Massive reference stores MIC codes — show the household exchange names.
const EXCHANGE_LABEL: Record<string, string> = {
  XNYS: "NYSE",
  XNAS: "NASDAQ",
  XASE: "NYSE American",
  ARCX: "NYSE Arca",
  BATS: "Cboe BZX",
};

export default function SignalDetailPage({ params }: Props) {
  const { ticker } = use(params);
  const T = ticker.toUpperCase();

  const [signal, setSignal] = useState<Signal | null>(null);
  const [view, setView] = useState<View>("loading");
  const [reason, setReason] = useState<"not_in_universe" | "delisted">("not_in_universe");
  const [requiredTier, setRequiredTier] = useState("PRO");
  const [attempt, setAttempt] = useState(0); // bump to re-run the signal load (Retry)

  const watchlist = useWatchlist();
  const watched = watchlist.has(T);

  // The ticker is confirmed covered (in our universe) once the signal endpoint
  // answers anything but 404 — only then fire the secondary data queries, so a
  // junk symbol like /signals/ZZZZZ never triggers on-demand news fetches.
  const covered = view === "live" || view === "computing" || view === "locked";

  const { data: info } = useQuery<Ticker>({
    queryKey: ["tickerInfo", T],
    queryFn: () => tickerApi.get(T),
    staleTime: 60 * 60 * 1000,
    retry: false,
    enabled: covered,
  });

  const { data: tickerNews } = useQuery({
    queryKey: ["tickerNews", T],
    queryFn: () => news.byTicker(T, 7),
    staleTime: 5 * 60 * 1000,
    enabled: covered,
  });

  const { data: tickerEarnings } = useQuery<EarningsEvent[]>({
    queryKey: ["tickerEarnings", T],
    queryFn: () => earningsApi.byTicker(T),
    staleTime: 10 * 60 * 1000,
    enabled: covered,
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
            // Took too long — surface an honest "try again" state, never fake data.
            setView("error");
          }
        } else if (err.status === 403) {
          // Signal exists but the caller's tier is too low — upgrade CTA, never
          // fake data. Detail reads like "Tier 'PRO' required".
          const m = /Tier '(\w+)'/.exec(err.data?.detail ?? "");
          setRequiredTier(m?.[1] ?? "PRO");
          setView("locked");
        } else {
          // Network / server error — show an honest error state with a Retry, never
          // fabricate ML output for a signals product.
          setView("error");
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
  }, [T, attempt]);

  const toggleWatch = () => {
    (watched ? watchlist.remove(T) : watchlist.add(T)).catch(() => {});
  };

  // Unknown / delisted symbol → dedicated view, rendered in place (URL stays /signals/T).
  if (view === "unknown") {
    return <UnknownSymbol symbol={T} reason={reason} />;
  }

  const companyName = info && info.name !== T ? info.name : null;
  const headerMeta = info
    ? [
        info.exchange ? (EXCHANGE_LABEL[info.exchange] ?? info.exchange) : null,
        info.sector,
        info.market_cap != null ? `Mkt cap $${compact(info.market_cap)}` : null,
      ].filter(Boolean)
    : [];

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <Link
        href="/"
        className="text-sm text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 flex items-center gap-1 w-fit transition-colors"
      >
        <ArrowLeft size={14} /> Dashboard
      </Link>

      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-3 flex-wrap">
            <h1 className="text-3xl font-bold font-mono text-zinc-900 dark:text-white">{T}</h1>
            {companyName && (
              <span className="text-lg text-zinc-600 dark:text-zinc-400 truncate">{companyName}</span>
            )}
          </div>
          {headerMeta.length > 0 && (
            <p className="text-xs text-zinc-500 mt-1">
              {headerMeta.join(" · ")}
            </p>
          )}
        </div>
        <button
          onClick={toggleWatch}
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

      {view === "locked" ? (
        <Card className="h-56 grid place-items-center text-center">
          <div className="flex flex-col items-center gap-3">
            <span className="w-10 h-10 rounded-full bg-amber-500/10 border border-amber-500/30 grid place-items-center">
              <Lock size={18} className="text-amber-500 dark:text-amber-400" />
            </span>
            <p className="text-sm text-zinc-700 dark:text-zinc-300">
              The <span className="font-mono font-semibold">{T}</span> signal requires the{" "}
              <span className="font-semibold text-amber-600 dark:text-amber-400">{requiredTier}</span> plan.
            </p>
            <Link
              href="/pricing"
              className="px-4 py-2 rounded-lg text-xs font-semibold bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30 hover:bg-amber-500/25 transition-colors"
            >
              Upgrade to {requiredTier}
            </Link>
          </div>
        </Card>
      ) : view === "computing" && !signal ? (
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

      {covered && tickerNews && tickerNews.length > 0 && (
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

          <NewsSentimentBar articles={tickerNews} />

          <div className="space-y-3">
            {tickerNews.slice(0, 6).map((article: NewsApiArticle) => {
              const sent = article.sentiment ?? "neutral";
              return (
                <div key={article.id} className="flex items-start gap-2.5">
                  <span className={cn(
                    "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                    sent === "positive" ? "bg-emerald-500" : sent === "negative" ? "bg-red-500" : "bg-zinc-500",
                  )} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <div className="min-w-0 flex-1">
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
                      </div>
                      {sent !== "neutral" && (
                        <span className={cn(
                          "shrink-0 px-1.5 py-0.5 rounded-full text-[10px] font-semibold border",
                          sent === "positive"
                            ? "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
                            : "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30",
                        )}>
                          {sent === "positive" ? "Bullish" : "Bearish"}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-zinc-400 dark:text-zinc-600 mt-0.5">
                      {article.source} · {timeAgoUnix(article.datetime)}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {covered && <CelebritySection ticker={T} />}

      {covered && tickerEarnings && tickerEarnings.length > 0 && (
        <EarningsSection ticker={T} earnings={tickerEarnings} />
      )}

      <p className="text-xs text-zinc-400 dark:text-zinc-600 text-center">
        {view === "live"
          ? "Live signal from the API."
          : view === "computing"
            ? "Waiting on live ML output…"
            : view === "locked"
              ? `Signal locked — requires the ${requiredTier} plan.`
              : "Demo signal — connect the backend for live ML output."}
      </p>
    </div>
  );
}

/* ── Smart money (celebrity holdings) section ─────────────────────── */

const ACTION_STYLE: Record<CelebAction, string> = {
  BUY: "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  SELL: "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30",
  HOLD: "text-zinc-500 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50",
};

function CelebritySection({ ticker }: { ticker: string }) {
  const { data } = useQuery<CelebrityHolding[]>({
    queryKey: ["celebByTicker", ticker],
    queryFn: () => celebApi.byTicker(ticker, 30),
    staleTime: 10 * 60 * 1000,
  });

  const holdings = data ?? [];
  if (holdings.length === 0) return null;

  const buys = holdings.filter((h) => h.action === "BUY").length;
  const sells = holdings.filter((h) => h.action === "SELL").length;

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
          <Crown size={15} className="text-amber-500 dark:text-amber-400" />
          Smart Money Activity in {ticker}
        </h3>
        <Link
          href="/celebrity-holdings"
          className="text-xs text-zinc-500 hover:text-sky-500 flex items-center gap-1 transition-colors"
        >
          View all <ArrowRight size={12} />
        </Link>
      </div>
      <p className="text-xs text-zinc-500 mb-2">
        <span className="text-emerald-600 dark:text-emerald-400 font-mono">{buys}</span> buys ·{" "}
        <span className="text-red-600 dark:text-red-400 font-mono">{sells}</span> sells in recent filings
      </p>

      <div className="divide-y divide-zinc-100 dark:divide-zinc-800/50">
        {holdings.slice(0, 8).map((h) => {
          const meta = getCelebrityMeta(h.celebrity);
          const color = getCelebrityColor(h.celebrity);
          return (
            <div key={h.id} className="flex items-center gap-3 py-2.5">
              <Link
                href={`/celebrity-holdings/${h.celebrity}`}
                className="flex items-center gap-2.5 min-w-0 flex-1 group"
              >
                <span className={cn(
                  "w-7 h-7 rounded-full bg-gradient-to-br grid place-items-center text-[9px] font-bold text-white shrink-0",
                  color,
                )}>
                  {meta.avatar}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-200 group-hover:text-sky-500 dark:group-hover:text-sky-400 transition-colors truncate">
                    {meta.name}
                  </span>
                  <span className="block text-[11px] text-zinc-500 truncate">{meta.title}</span>
                </span>
              </Link>
              <span className={cn(
                "shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold border leading-none",
                ACTION_STYLE[h.action],
              )}>
                {h.action}
              </span>
              <span className="text-right w-24 shrink-0">
                <span className="block font-mono text-xs text-zinc-700 dark:text-zinc-300">
                  {h.value_usd != null
                    ? `$${compact(h.value_usd)}`
                    : h.shares != null
                      ? `${compact(h.shares)} sh`
                      : "—"}
                </span>
                <span className="block text-[10px] text-zinc-400 dark:text-zinc-600">
                  {h.source_type === "13F" ? "13F filing" : "disclosure"}
                </span>
              </span>
              <span className="text-right w-20 shrink-0 flex items-center justify-end gap-1.5">
                <span className="text-xs text-zinc-500">{timeAgo(h.reported_at)}</span>
                {h.filing_url && (
                  <a
                    href={h.filing_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-zinc-400 hover:text-sky-500 transition-colors"
                    title="View filing"
                  >
                    <ExternalLink size={11} />
                  </a>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
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

// Same conventions as the earnings calendar page (app/earnings/page.tsx).
const statusOf = (e: EarningsEvent) =>
  e.status ?? (e.eps_actual !== null ? "REPORTED" : "UPCOMING");

function earningsUrl(ticker: string) {
  return `https://www.nasdaq.com/market-activity/stocks/${ticker.toLowerCase()}/earnings`;
}

function quarterShort(e: EarningsEvent) {
  if (e.fiscal_quarter == null || e.fiscal_year == null) return null;
  return `Q${e.fiscal_quarter}'${String(e.fiscal_year).slice(2)}`;
}

function daysUntil(today: string | null, reportDate: string) {
  if (!today) return null;
  const t = new Date(today + "T00:00:00Z").getTime();
  const r = new Date(reportDate + "T00:00:00Z").getTime();
  return Math.ceil((r - t) / 864e5);
}

function EarningsSection({ ticker, earnings }: { ticker: string; earnings: EarningsEvent[] }) {
  const [today, setToday] = useState<string | null>(null);
  useEffect(() => setToday(new Date().toISOString().slice(0, 10)), []);

  // Backend-computed lifecycle status is the source of truth: PENDING rows
  // (date passed, actuals never landed) must NOT surface as the next report.
  const reported = earnings.filter((e) => statusOf(e) === "REPORTED");
  const upcoming = earnings.filter((e) => statusOf(e) === "UPCOMING");
  // earnings come newest-first, so the soonest upcoming is the last element.
  const next = upcoming.length > 0 ? upcoming[upcoming.length - 1] : null;
  const nextDays = next ? daysUntil(today, next.report_date) : null;

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
          <CalendarDays size={15} className="text-sky-500" />
          Earnings for {ticker}
        </h3>
        <div className="flex items-center gap-4">
          <a
            href={earningsUrl(ticker)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-zinc-500 hover:text-sky-500 flex items-center gap-1 transition-colors"
            title="View earnings on Nasdaq"
          >
            Nasdaq <ExternalLink size={12} />
          </a>
          <Link
            href="/earnings"
            className="text-xs text-zinc-500 hover:text-sky-500 flex items-center gap-1 transition-colors"
          >
            Calendar <ArrowRight size={12} />
          </Link>
        </div>
      </div>

      {/* Next upcoming */}
      {next && (
        <div className="mb-3 px-3 py-2.5 rounded-lg bg-sky-500/5 border border-sky-500/20">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-semibold text-sky-600 dark:text-sky-400 uppercase tracking-wider">
                Next Report
              </span>
              <span className="font-mono text-sm text-zinc-800 dark:text-zinc-200">
                {next.report_date}
              </span>
              {next.session && <SessionBadge session={next.session} />}
              {quarterShort(next) && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-zinc-700 leading-none">
                  {quarterShort(next)}
                </span>
              )}
              {nextDays != null && nextDays >= 0 && (
                <span className={cn(
                  "flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-semibold border",
                  nextDays <= 1
                    ? "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/30"
                    : nextDays <= 7
                      ? "text-sky-600 dark:text-sky-400 bg-sky-500/10 border-sky-500/30"
                      : "text-zinc-500 bg-zinc-100 dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700",
                )}>
                  <Clock size={10} />
                  {nextDays === 0 ? "Today" : nextDays === 1 ? "Tomorrow" : `in ${nextDays}d`}
                </span>
              )}
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
            <div className="col-span-3 text-right">EPS Act / Est</div>
            <div className="col-span-2 text-right">Surprise</div>
            <div className="col-span-2 text-right">Revenue</div>
            <div className="col-span-2 text-right">Reaction</div>
          </div>
          {reported.slice(0, 4).map((e) => {
            const s = e.eps_surprise_pct;
            const reaction = e.reaction_close_pct;
            return (
              <div
                key={e.report_date}
                className="grid grid-cols-12 gap-1 px-3 py-2 border-t border-zinc-100 dark:border-zinc-800/40 text-xs"
              >
                <div className="col-span-3 font-mono text-zinc-600 dark:text-zinc-400 flex items-center gap-1.5">
                  {e.report_date.slice(5)}
                  <span className="text-zinc-400 dark:text-zinc-600">{quarterShort(e)}</span>
                  {e.session && <span className="hidden sm:inline-flex"><SessionBadge session={e.session} small /></span>}
                </div>
                <div className="col-span-3 text-right font-mono">
                  <span className="font-semibold text-zinc-900 dark:text-zinc-100">${e.eps_actual!.toFixed(2)}</span>
                  <span className="text-zinc-400 dark:text-zinc-600">
                    {" "}/ {e.eps_estimate != null ? `$${e.eps_estimate.toFixed(2)}` : "—"}
                  </span>
                </div>
                <div className="col-span-2 text-right">
                  {s != null ? (
                    <span className={cn(
                      "inline-flex items-center gap-0.5 font-mono font-semibold",
                      s >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400",
                    )}>
                      {s >= 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                      {signedPct(s, 1)}
                    </span>
                  ) : (
                    <span className="text-zinc-400 dark:text-zinc-600">—</span>
                  )}
                </div>
                <div className="col-span-2 text-right font-mono text-zinc-500">
                  {e.revenue_actual != null
                    ? `$${compact(e.revenue_actual)}`
                    : e.revenue_estimate != null
                      ? `~$${compact(e.revenue_estimate)}`
                      : "—"}
                </div>
                <div className="col-span-2 text-right">
                  {reaction != null ? (
                    <span
                      className={cn(
                        "font-mono font-semibold",
                        reaction >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400",
                      )}
                      title={e.reaction_open_pct != null
                        ? `1-day move; gap at open ${signedPct(e.reaction_open_pct, 2)}`
                        : "1-day move vs pre-earnings close"}
                    >
                      {signedPct(reaction, 2)}
                    </span>
                  ) : e.reaction_status === "pending" ? (
                    <span className="text-zinc-500" title="Available after the next session closes">
                      Pending
                    </span>
                  ) : (
                    <span className="text-zinc-400 dark:text-zinc-600">—</span>
                  )}
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
