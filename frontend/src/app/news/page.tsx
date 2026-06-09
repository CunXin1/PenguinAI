"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Newspaper, ArrowRight, ExternalLink } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { news as newsApi } from "@/lib/api";
import { MOCK_NEWS } from "@/lib/mock";
import { cn, timeAgoUnix } from "@/lib/utils";
import type { NewsArticle, NewsApiArticle } from "@/lib/types";

const SENT: Record<NewsArticle["sentiment"], { label: string; chip: string }> = {
  positive: { label: "Bullish", chip: "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30" },
  negative: { label: "Bearish", chip: "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30" },
  neutral: { label: "Neutral", chip: "text-zinc-600 dark:text-zinc-400 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50" },
};

const FILTERS = ["all", "positive", "negative", "neutral"] as const;

/** Map a raw Finnhub API article to the frontend NewsArticle shape. */
function mapApiArticle(raw: NewsApiArticle): NewsArticle {
  return {
    id: raw.id,
    headline: raw.headline,
    summary: raw.summary,
    source: raw.source,
    url: raw.url,
    image: raw.image,
    datetime: raw.datetime,
    time: timeAgoUnix(raw.datetime),
    sentiment: "neutral", // FinBERT not yet online — default neutral
    tickers: raw.tickers,
    category: raw.category,
  };
}

export default function NewsPage() {
  const [f, setF] = useState<(typeof FILTERS)[number]>("all");

  const { data: articles, isLoading } = useQuery<NewsArticle[]>({
    queryKey: ["marketNews"],
    queryFn: async () => {
      const raw = await newsApi.market();
      return raw.map(mapApiArticle);
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Fall back to mock data when the API fails or is loading
  const allNews = articles ?? MOCK_NEWS;

  const counts = useMemo(
    () => ({
      positive: allNews.filter((n) => n.sentiment === "positive").length,
      negative: allNews.filter((n) => n.sentiment === "negative").length,
      neutral: allNews.filter((n) => n.sentiment === "neutral").length,
    }),
    [allNews]
  );
  const total = allNews.length;
  const net = counts.positive >= counts.negative ? "Bullish" : "Bearish";

  const [featured, ...rest] = allNews;
  const feed = f === "all" ? rest : allNews.filter((n) => n.sentiment === f);

  /** Resolve the link target for a news card. External URL if available, otherwise internal route. */
  const articleHref = (n: NewsArticle) => n.url ?? `/news/${n.id}`;
  const isExternal = (n: NewsArticle) => Boolean(n.url);

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
          <div className="bg-emerald-500" style={{ width: `${total > 0 ? (counts.positive / total) * 100 : 0}%` }} />
          <div className="bg-zinc-400 dark:bg-zinc-600" style={{ width: `${total > 0 ? (counts.neutral / total) * 100 : 0}%` }} />
          <div className="bg-red-500" style={{ width: `${total > 0 ? (counts.negative / total) * 100 : 0}%` }} />
        </div>
        <div className="flex gap-4 mt-2 text-xs text-zinc-500">
          <span><span className="text-emerald-600 dark:text-emerald-400 font-mono">{counts.positive}</span> bullish</span>
          <span><span className="text-zinc-700 dark:text-zinc-300 font-mono">{counts.neutral}</span> neutral</span>
          <span><span className="text-red-600 dark:text-red-400 font-mono">{counts.negative}</span> bearish</span>
        </div>
      </Card>

      {/* Loading state */}
      {isLoading && !articles && (
        <div className="text-center py-4">
          <p className="text-sm text-zinc-400 dark:text-zinc-600 animate-pulse">Loading news...</p>
        </div>
      )}

      {/* Featured */}
      {f === "all" && featured && (
        <a
          href={articleHref(featured)}
          {...(isExternal(featured) ? { target: "_blank", rel: "noopener noreferrer" } : {})}
          className="block group"
        >
          <Card className="p-5 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
            <div className="flex items-center gap-2 mb-2">
              <span className={cn("px-2 py-0.5 rounded-full text-[11px] font-semibold border", SENT[featured.sentiment].chip)}>
                {SENT[featured.sentiment].label}
              </span>
              <span className="text-xs text-zinc-400 dark:text-zinc-600">Featured · {featured.source}</span>
              {isExternal(featured) && <ExternalLink size={12} className="text-zinc-400 dark:text-zinc-600" />}
            </div>
            {featured.image && (
              <Image
                src={featured.image}
                alt=""
                width={800}
                height={192}
                className="w-full h-48 object-cover rounded-md mb-3"
                unoptimized
              />
            )}
            <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100 leading-snug group-hover:text-zinc-900 dark:group-hover:text-white transition-colors">{featured.headline}</h2>
            <p className="text-sm text-zinc-600 dark:text-zinc-400 mt-2 leading-relaxed">{featured.summary}</p>
            <span className="inline-flex items-center gap-1 text-sm text-sky-600 dark:text-sky-400 mt-3">
              {isExternal(featured) ? "Read on source" : "Read article"} <ArrowRight size={14} />
            </span>
          </Card>
        </a>
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
          const ext = isExternal(n);
          const LinkOrA = ext ? "a" : Link;
          const linkProps = ext
            ? { href: n.url!, target: "_blank" as const, rel: "noopener noreferrer" }
            : { href: `/news/${n.id}` };

          return (
            <LinkOrA key={n.id} {...linkProps} className="block group">
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
                      {ext && <ExternalLink size={11} className="text-zinc-400 dark:text-zinc-600 ml-1" />}
                    </div>
                  </div>
                  <span className={cn("shrink-0 px-2 py-0.5 rounded-full text-[11px] font-semibold border", s.chip)}>{s.label}</span>
                </div>
              </Card>
            </LinkOrA>
          );
        })}
        {feed.length === 0 && <p className="text-center text-sm text-zinc-400 dark:text-zinc-600 py-8">No {f} headlines right now.</p>}
      </div>
    </div>
  );
}
