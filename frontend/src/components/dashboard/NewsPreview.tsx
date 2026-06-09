"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Newspaper, ArrowRight, ExternalLink } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { news as newsApi } from "@/lib/api";
import { timeAgoUnix } from "@/lib/utils";

export function NewsPreview() {
  const { data: apiArticles, isLoading } = useQuery({
    queryKey: ["dashboardNews"],
    queryFn: () => newsApi.market("general"),
    staleTime: 5 * 60 * 1000,
  });

  const articles = (apiArticles ?? []).slice(0, 5).map((a) => ({
    id: a.id,
    headline: a.headline,
    source: a.source,
    time: timeAgoUnix(a.datetime),
    url: a.url,
    tickers: a.tickers,
  }));

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
          <Newspaper size={15} className="text-sky-500 dark:text-sky-400" />
          Latest News
        </h3>
        <Link
          href="/news"
          className="text-xs text-zinc-500 hover:text-sky-600 dark:hover:text-sky-400 flex items-center gap-1 transition-colors"
        >
          All <ArrowRight size={12} />
        </Link>
      </div>
      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 rounded bg-zinc-100 dark:bg-zinc-800/60 animate-pulse" />
          ))}
        </div>
      ) : articles.length === 0 ? (
        <p className="text-sm text-zinc-400 dark:text-zinc-600 py-4 text-center">No news available.</p>
      ) : (
        <div className="space-y-3">
          {articles.map((n) => (
            <a
              key={n.id}
              href={n.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block group"
            >
              <div className="flex gap-2.5">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 bg-zinc-500" />
                <div className="min-w-0">
                  <p className="text-sm text-zinc-700 dark:text-zinc-300 leading-snug group-hover:text-zinc-900 dark:group-hover:text-white transition-colors line-clamp-2">
                    {n.headline}
                    <ExternalLink
                      size={10}
                      className="inline ml-1 -mt-0.5 text-zinc-400"
                    />
                  </p>
                  <p className="text-[11px] text-zinc-400 dark:text-zinc-600 mt-0.5">
                    {n.source} · {n.time}
                    {n.tickers && n.tickers.length > 0
                      ? ` · ${n.tickers.join(", ")}`
                      : ""}
                  </p>
                </div>
              </div>
            </a>
          ))}
        </div>
      )}
    </Card>
  );
}
