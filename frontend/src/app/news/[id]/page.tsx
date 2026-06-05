import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { MOCK_NEWS, MOCK_UNIVERSE } from "@/lib/mock";
import { cn } from "@/lib/utils";
import type { NewsArticle } from "@/lib/types";

const SENT: Record<NewsArticle["sentiment"], { label: string; cls: string }> = {
  positive: { label: "Bullish", cls: "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30" },
  negative: { label: "Bearish", cls: "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30" },
  neutral: { label: "Neutral", cls: "text-zinc-600 dark:text-zinc-400 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50" },
};

export default async function NewsArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const article = MOCK_NEWS.find((n) => n.id === id);
  if (!article) notFound();

  const s = SENT[article.sentiment];
  const related = (article.tickers ?? [])
    .map((t) => MOCK_UNIVERSE.find((u) => u.ticker === t))
    .filter((u): u is NonNullable<typeof u> => Boolean(u));
  const paragraphs = (article.body ?? article.summary).split("\n\n");

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-5">
      <Link href="/news" className="text-sm text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 flex items-center gap-1 w-fit transition-colors">
        <ArrowLeft size={14} /> News
      </Link>

      <div className="space-y-3">
        <span className={cn("inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold border", s.cls)}>{s.label}</span>
        <h1 className="text-2xl font-bold text-zinc-900 dark:text-white leading-tight">{article.headline}</h1>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span className="text-zinc-700 dark:text-zinc-300">{article.source}</span>
          <span>·</span>
          <span>{article.time}</span>
        </div>
      </div>

      <article className="space-y-4">
        {paragraphs.map((p, i) => (
          <p key={i} className="text-[15px] text-zinc-700 dark:text-zinc-300 leading-relaxed">
            {p}
          </p>
        ))}
      </article>

      {related.length > 0 && (
        <Card className="p-4">
          <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-200 mb-3">Related signals</p>
          <div className="space-y-1">
            {related.map((u) => (
              <Link
                key={u.ticker}
                href={`/signals/${u.ticker}`}
                className="flex items-center justify-between py-2 px-2 -mx-2 rounded-md hover:bg-zinc-100 dark:hover:bg-zinc-800/40 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="font-mono font-semibold text-sm text-zinc-900 dark:text-zinc-100 w-14 shrink-0">{u.ticker}</span>
                  <span className="text-xs text-zinc-500 truncate">{u.name}</span>
                </div>
                <DirectionBadge direction={u.direction} />
              </Link>
            ))}
          </div>
        </Card>
      )}

      <p className="text-xs text-zinc-400 dark:text-zinc-600 pt-3 border-t border-zinc-200 dark:border-zinc-800/60">
        Demo article · in production this renders from the <span className="font-mono">news_articles</span> table with FinBERT
        scoring and pgvector retrieval.
      </p>
    </div>
  );
}
