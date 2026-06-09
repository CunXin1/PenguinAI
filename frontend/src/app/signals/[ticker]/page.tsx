"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Star, Loader2, Newspaper, ExternalLink } from "lucide-react";
import { signals as signalApi, news } from "@/lib/api";
import { PriceChart } from "@/components/charts/PriceChart";
import { SignalCard } from "@/components/signals/SignalCard";
import { UnknownSymbol } from "@/components/signals/UnknownSymbol";
import { Card } from "@/components/ui/Card";
import { mockSignalDetail } from "@/lib/mock";
import { timeAgoUnix } from "@/lib/utils";
import type { ApiError, NewsApiArticle, Signal } from "@/lib/types";

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
