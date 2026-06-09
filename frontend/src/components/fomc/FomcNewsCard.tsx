"use client";

import { useQuery } from "@tanstack/react-query";
import { Newspaper, ExternalLink } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { timeAgoUnix } from "@/lib/utils";
import type { NewsApiArticle } from "@/lib/types";

export function FomcNewsCard() {
  const { data: articles, isLoading } = useQuery<NewsApiArticle[]>({
    queryKey: ["fomcNews"],
    queryFn: () => fomcApi.news(10),
    staleTime: 15 * 60 * 1000,
  });

  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2 mb-3">
        <Newspaper size={15} className="text-sky-600 dark:text-sky-400" />
        Fed & FOMC News
      </h3>

      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 rounded bg-zinc-100 dark:bg-zinc-800/60 animate-pulse" />
          ))}
        </div>
      ) : !articles || articles.length === 0 ? (
        <p className="text-sm text-zinc-400 dark:text-zinc-600 py-4 text-center">No Fed news available.</p>
      ) : (
        <div className="space-y-3">
          {articles.map((a) => (
            <a
              key={a.id}
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block group"
            >
              <div className="flex gap-2.5">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 bg-sky-500/60" />
                <div className="min-w-0">
                  <p className="text-sm text-zinc-700 dark:text-zinc-300 leading-snug group-hover:text-zinc-900 dark:group-hover:text-white transition-colors line-clamp-2">
                    {a.headline}
                    <ExternalLink size={10} className="inline ml-1 -mt-0.5 text-zinc-400" />
                  </p>
                  <p className="text-[11px] text-zinc-400 dark:text-zinc-600 mt-0.5">
                    {a.source} · {timeAgoUnix(a.datetime)}
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
