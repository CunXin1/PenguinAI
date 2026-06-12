"use client";

import { ExternalLink } from "lucide-react";
import { PriceChart } from "@/components/charts/PriceChart";
import { cn } from "@/lib/utils";
import type { ChartRange, ChatCard, ChatNewsItem } from "@/lib/types";

// Map the tool's history range onto a range PriceChart supports.
const RANGE_MAP: Record<string, ChartRange> = {
  "1W": "1W",
  "1M": "1M",
  "3M": "3M",
  "6M": "3M",
  "1Y": "1Y",
  MAX: "1Y",
};

function sentimentClass(label?: string | null): string {
  const l = (label ?? "").toLowerCase();
  if (l === "positive") return "text-emerald-500 dark:text-emerald-400";
  if (l === "negative") return "text-red-500 dark:text-red-400";
  return "text-zinc-400 dark:text-zinc-500";
}

function NewsCard({ ticker, articles }: { ticker: string; articles: ChatNewsItem[] }) {
  if (!articles?.length) return null;
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 overflow-hidden">
      <div className="px-3 py-2 text-[11px] font-medium text-zinc-500 dark:text-zinc-400 border-b border-zinc-200 dark:border-zinc-800">
        {ticker} · recent news
      </div>
      <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/70">
        {articles.map((a, i) => {
          const row = (
            <div className="px-3 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-800/40 transition-colors">
              <div className="flex items-start gap-2">
                <span className="text-sm text-zinc-800 dark:text-zinc-200 leading-snug flex-1">
                  {a.headline}
                </span>
                {a.url && <ExternalLink size={12} className="mt-0.5 shrink-0 text-zinc-400" />}
              </div>
              <div className="mt-1 flex items-center gap-2 text-[10px]">
                <span className="text-zinc-400 dark:text-zinc-500">{a.source}</span>
                {a.finbert_label && (
                  <span className={cn("uppercase tracking-wide", sentimentClass(a.finbert_label))}>
                    {a.finbert_label}
                  </span>
                )}
              </div>
            </div>
          );
          return (
            <li key={i}>
              {a.url ? (
                <a href={a.url} target="_blank" rel="noopener noreferrer" className="block">
                  {row}
                </a>
              ) : (
                row
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Render the rich cards an assistant turn emitted, inline below its bubble. */
export function ChatCards({ cards }: { cards: ChatCard[] }) {
  if (!cards?.length) return null;
  return (
    <div className="space-y-2 pt-1">
      {cards.map((c, i) => {
        if (c.card === "chart") {
          return (
            <div
              key={i}
              className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/40 p-2"
            >
              <PriceChart
                ticker={c.data.ticker}
                defaultRange={RANGE_MAP[c.data.range] ?? "1W"}
                height={220}
              />
            </div>
          );
        }
        return <NewsCard key={i} ticker={c.data.ticker} articles={c.data.articles} />;
      })}
    </div>
  );
}
