"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, TrendingDown, GitCompareArrows, ExternalLink, ChevronDown } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FomcStatement, FomcDiffResult } from "@/lib/types";

function scoreLabel(score: number): string {
  if (score >= 0.3) return "Hawkish";
  if (score >= 0.1) return "Slightly Hawkish";
  if (score > -0.1) return "Neutral";
  if (score > -0.3) return "Slightly Dovish";
  return "Dovish";
}

function scoreColor(score: number): string {
  if (score >= 0.3) return "text-red-600 dark:text-red-400";
  if (score >= 0.1) return "text-orange-600 dark:text-orange-400";
  if (score > -0.1) return "text-zinc-600 dark:text-zinc-400";
  if (score > -0.3) return "text-sky-600 dark:text-sky-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr + "T12:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return dateStr;
  }
}

function StatementDiff({ date }: { date: string }) {
  const { data: diff, isLoading } = useQuery<FomcDiffResult>({
    queryKey: ["fomcDiff", date],
    queryFn: () => fomcApi.diff(date),
    staleTime: 60 * 60 * 1000,
  });

  if (isLoading) {
    return <p className="text-xs text-zinc-400 dark:text-zinc-500 animate-pulse py-2">Loading diff...</p>;
  }
  if (!diff || !diff.diff) return null;

  const added = diff.diff.filter((d) => d.type === "added").length;
  const removed = diff.diff.filter((d) => d.type === "removed").length;

  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-2 text-[11px] text-zinc-500">
        <span>vs. {diff.previous_date ? formatDate(diff.previous_date) : "N/A"}</span>
        {added > 0 && <span className="text-emerald-500">+{added} added</span>}
        {removed > 0 && <span className="text-red-500">-{removed} removed</span>}
        {added === 0 && removed === 0 && <span>No changes</span>}
      </div>
      <div className="text-xs leading-relaxed space-y-0.5">
        {diff.diff.map((line, i) => (
          <span
            key={i}
            className={cn(
              "inline",
              line.type === "added" && "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
              line.type === "removed" && "bg-red-500/15 text-red-700 dark:text-red-300 line-through",
              line.type === "unchanged" && "text-zinc-500",
            )}
          >
            {line.text}{" "}
          </span>
        ))}
      </div>
    </div>
  );
}

export function StatementList() {
  const [limit, setLimit] = useState(10);
  const [diffDate, setDiffDate] = useState<string | null>(null);

  const { data: statements, isLoading } = useQuery<FomcStatement[]>({
    queryKey: ["fomcStatements", limit],
    queryFn: () => fomcApi.statements(limit),
    staleTime: 60 * 60 * 1000,
  });

  return (
    <div>
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-3">Past Statements</h3>

      {isLoading && (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-20 rounded-xl bg-zinc-100 dark:bg-zinc-800/60 animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && (!statements || statements.length === 0) && (
        <Card className="p-5">
          <p className="text-sm text-zinc-500 text-center">
            No FOMC statements loaded. Run the FOMC scraper to populate data.
          </p>
        </Card>
      )}

      {statements && statements.length > 0 && (
        <div className="space-y-3">
          {statements.map((s) => (
            <Card key={s.date} className="p-4 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1.5 min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                      {formatDate(s.date)}
                    </span>
                    {s.hawk_dove_score !== null && (
                      <span className={cn(
                        "inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[11px] font-semibold border",
                        s.hawk_dove_score >= 0
                          ? "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30"
                          : "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
                      )}>
                        {s.hawk_dove_score >= 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                        {scoreLabel(s.hawk_dove_score)}
                      </span>
                    )}
                    <button
                      onClick={() => setDiffDate(diffDate === s.date ? null : s.date)}
                      className={cn(
                        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] border transition-colors",
                        diffDate === s.date
                          ? "bg-sky-500/10 border-sky-500/30 text-sky-600 dark:text-sky-400"
                          : "border-zinc-200 dark:border-zinc-700 text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300",
                      )}
                    >
                      <GitCompareArrows size={10} />
                      Diff
                    </button>
                  </div>
                  {s.summary && (
                    <p className="text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed">{s.summary}</p>
                  )}
                  {s.document_url && (
                    <a
                      href={s.document_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-sky-600 dark:text-sky-400 hover:underline mt-1"
                    >
                      View statement <ExternalLink size={10} />
                    </a>
                  )}
                  {diffDate === s.date && <StatementDiff date={s.date} />}
                </div>
                {s.hawk_dove_score !== null && (
                  <div className="shrink-0 text-right">
                    <div className={cn("text-lg font-bold font-mono", scoreColor(s.hawk_dove_score))}>
                      {s.hawk_dove_score >= 0 ? "+" : ""}{s.hawk_dove_score.toFixed(2)}
                    </div>
                    <div className="text-[10px] text-zinc-500">score</div>
                  </div>
                )}
              </div>
            </Card>
          ))}

          <button
            onClick={() => setLimit((l) => l + 10)}
            className="w-full py-2.5 rounded-xl border border-zinc-200 dark:border-zinc-800 text-sm text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-200 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors flex items-center justify-center gap-1.5"
          >
            <ChevronDown size={14} />
            Show more
          </button>
        </div>
      )}
    </div>
  );
}
