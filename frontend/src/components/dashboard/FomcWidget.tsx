"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Landmark, ArrowRight, Clock, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FomcNextMeeting, FomcStatement, FomcTrendPoint } from "@/lib/types";

function scoreColor(score: number): string {
  if (score >= 0.3) return "text-red-500";
  if (score >= 0.1) return "text-orange-400";
  if (score > -0.1) return "text-zinc-400";
  if (score > -0.3) return "text-sky-400";
  return "text-emerald-400";
}

function stanceLabel(score: number): string {
  if (score >= 0.3) return "Hawkish";
  if (score >= 0.1) return "Slightly Hawkish";
  if (score > -0.1) return "Neutral";
  if (score > -0.3) return "Slightly Dovish";
  return "Dovish";
}

function StanceIcon({ score }: { score: number }) {
  if (score >= 0.1) return <TrendingUp size={14} />;
  if (score <= -0.1) return <TrendingDown size={14} />;
  return <Minus size={14} />;
}

export function FomcWidget() {
  const { data: nextMeeting } = useQuery<FomcNextMeeting>({
    queryKey: ["dashboardFomcNext"],
    queryFn: () => fomcApi.nextMeeting(),
    staleTime: 60 * 60 * 1000,
  });

  const { data: statements, isLoading } = useQuery<FomcStatement[]>({
    queryKey: ["dashboardFomcStatements"],
    queryFn: () => fomcApi.statements(3),
    staleTime: 60 * 60 * 1000,
  });

  const { data: trend } = useQuery<FomcTrendPoint[]>({
    queryKey: ["dashboardFomcTrend"],
    queryFn: () => fomcApi.trend(8),
    staleTime: 60 * 60 * 1000,
  });

  const latest = statements?.[0];
  const latestScore = latest?.hawk_dove_score;

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-2">
          <Landmark size={15} className="text-sky-500 dark:text-sky-400" />
          FOMC Watch
        </h3>
        <Link
          href="/fomc"
          className="text-xs text-zinc-500 hover:text-sky-600 dark:hover:text-sky-400 flex items-center gap-1 transition-colors"
        >
          Details <ArrowRight size={12} />
        </Link>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-6 rounded bg-zinc-100 dark:bg-zinc-800/60 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {/* Current stance */}
          {latestScore != null && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">Current Stance</span>
              <span className={cn("flex items-center gap-1 text-sm font-semibold", scoreColor(latestScore))}>
                <StanceIcon score={latestScore} />
                {stanceLabel(latestScore)}
                <span className="font-mono text-xs ml-1">({latestScore >= 0 ? "+" : ""}{latestScore.toFixed(2)})</span>
              </span>
            </div>
          )}

          {/* Next meeting countdown */}
          {nextMeeting?.next_meeting && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500 flex items-center gap-1">
                <Clock size={11} /> Next Meeting
              </span>
              <span className="text-sm font-mono text-zinc-300">
                {nextMeeting.next_meeting}
                <span className="text-xs text-zinc-500 ml-1.5">
                  ({nextMeeting.days_until}d)
                </span>
              </span>
            </div>
          )}

          {/* Mini trend bar */}
          {trend && trend.length > 0 && (
            <div className="pt-1">
              <div className="flex items-end gap-px h-6">
                {trend.map((p) => {
                  const maxAbs = Math.max(0.3, ...trend.map((t) => Math.abs(t.score)));
                  const height = Math.max(2, (Math.abs(p.score) / maxAbs) * 100);
                  return (
                    <div
                      key={p.date}
                      className="flex-1 flex items-end justify-center"
                      title={`${p.date}: ${p.score >= 0 ? "+" : ""}${p.score.toFixed(2)}`}
                    >
                      <div
                        className={cn(
                          "w-full max-w-[6px] rounded-sm",
                          p.score >= 0 ? "bg-red-500/60" : "bg-emerald-500/60",
                        )}
                        style={{ height: `${height}%` }}
                      />
                    </div>
                  );
                })}
              </div>
              <div className="flex justify-between text-[9px] text-zinc-600 mt-0.5 px-0.5">
                <span>{trend[0]?.date.slice(5)}</span>
                <span>{trend[trend.length - 1]?.date.slice(5)}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
