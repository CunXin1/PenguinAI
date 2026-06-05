"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Newspaper, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { MOCK_NEWS } from "@/lib/mock";
import { cn } from "@/lib/utils";
import type { NewsArticle } from "@/lib/types";

const SENT: Record<NewsArticle["sentiment"], { label: string; chip: string }> = {
  positive: { label: "Bullish", chip: "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30" },
  negative: { label: "Bearish", chip: "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30" },
  neutral: { label: "Neutral", chip: "text-zinc-600 dark:text-zinc-400 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50" },
};

const FILTERS = ["all", "positive", "negative", "neutral"] as const;

export default function NewsPage() {
  const [f, setF] = useState<(typeof FILTERS)[number]>("all");

  const counts = useMemo(
    () => ({
      positive: MOCK_NEWS.filter((n) => n.sentiment === "positive").length,
      negative: MOCK_NEWS.filter((n) => n.sentiment === "negative").length,
      neutral: MOCK_NEWS.filter((n) => n.sentiment === "neutral").length,
    }),
    []
  );
  const total = MOCK_NEWS.length;
  const net = counts.positive >= counts.negative ? "Bullish" : "Bearish";

  const [featured, ...rest] = MOCK_NEWS;
  const feed = f === "all" ? rest : MOCK_NEWS.filter((n) => n.sentiment === f);

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <Newspaper size={20} className="text-sky-500 dark:text-sky-400" /> Market News
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">FinBERT-scored headlines from finance media &amp; social</p>
      </div>

      {/* Sentiment overview */}
      <Card className="p-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Today&apos;s news sentiment</p>
          <span className={cn("text-sm font-semibold", net === "Bullish" ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>{net} bias</span>
        </div>
        <div className="h-2 rounded-full overflow-hidden flex bg-zinc-200 dark:bg-zinc-800">
          <div className="bg-emerald-500" style={{ width: `${(counts.positive / total) * 100}%` }} />
          <div className="bg-zinc-400 dark:bg-zinc-600" style={{ width: `${(counts.neutral / total) * 100}%` }} />
          <div className="bg-red-500" style={{ width: `${(counts.negative / total) * 100}%` }} />
        </div>
        <div className="flex gap-4 mt-2 text-xs text-zinc-500">
          <span><span className="text-emerald-600 dark:text-emerald-400 font-mono">{counts.positive}</span> bullish</span>
          <span><span className="text-zinc-700 dark:text-zinc-300 font-mono">{counts.neutral}</span> neutral</span>
          <span><span className="text-red-600 dark:text-red-400 font-mono">{counts.negative}</span> bearish</span>
        </div>
      </Card>

      {/* Featured */}
      {f === "all" && (
        <Link href={`/news/${featured.id}`} className="block group">
          <Card className="p-5 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
            <div className="flex items-center gap-2 mb-2">
              <span className={cn("px-2 py-0.5 rounded-full text-[11px] font-semibold border", SENT[featured.sentiment].chip)}>
                {SENT[featured.sentiment].label}
              </span>
              <span className="text-xs text-zinc-400 dark:text-zinc-600">Featured · {featured.source}</span>
            </div>
            <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100 leading-snug group-hover:text-zinc-900 dark:group-hover:text-white transition-colors">{featured.headline}</h2>
            <p className="text-sm text-zinc-600 dark:text-zinc-400 mt-2 leading-relaxed">{featured.summary}</p>
            <span className="inline-flex items-center gap-1 text-sm text-sky-600 dark:text-sky-400 mt-3">
              Read article <ArrowRight size={14} />
            </span>
          </Card>
        </Link>
      )}

      {/* Filters */}
      <div className="flex gap-1">
        {FILTERS.map((x) => (
          <button
            key={x}
            onClick={() => setF(x)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
              f === x
                ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
            )}
          >
            {x === "all" ? "All" : SENT[x].label}
          </button>
        ))}
      </div>

      {/* Feed */}
      <div className="space-y-3">
        {feed.map((n) => {
          const s = SENT[n.sentiment];
          return (
            <Link key={n.id} href={`/news/${n.id}`} className="block group">
              <Card className="p-4 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1.5 min-w-0">
                    <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100 leading-snug group-hover:text-zinc-900 dark:group-hover:text-white transition-colors">{n.headline}</h2>
                    <p className="text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed line-clamp-2">{n.summary}</p>
                    <div className="flex items-center gap-2 text-xs text-zinc-400 dark:text-zinc-600 pt-1">
                      <span className="text-zinc-600 dark:text-zinc-400">{n.source}</span>
                      <span>·</span>
                      <span>{n.time}</span>
                      {n.tickers && n.tickers.length > 0 && (
                        <>
                          <span>·</span>
                          <span className="flex gap-1.5">
                            {n.tickers.map((t) => (
                              <span key={t} className="font-mono text-sky-600 dark:text-sky-400">{t}</span>
                            ))}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <span className={cn("shrink-0 px-2 py-0.5 rounded-full text-[11px] font-semibold border", s.chip)}>{s.label}</span>
                </div>
              </Card>
            </Link>
          );
        })}
        {feed.length === 0 && <p className="text-center text-sm text-zinc-400 dark:text-zinc-600 py-8">No {f} headlines right now.</p>}
      </div>
    </div>
  );
}
