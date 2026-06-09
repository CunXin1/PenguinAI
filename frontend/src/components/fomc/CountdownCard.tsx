"use client";

import { Clock, TrendingUp, TrendingDown } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/utils";
import type { FomcNextMeeting, FomcRatePoint, FomcRateProbability, FomcStatement } from "@/lib/types";

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr + "T12:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return dateStr;
  }
}

function fmtRate(low: number, high: number): string {
  if (low === high) return `${low.toFixed(2)}%`;
  return `${low.toFixed(2)}–${high.toFixed(2)}%`;
}

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

export function CountdownCard({
  meeting,
  ratePoints,
  probabilities,
  latestStatement,
}: {
  meeting: FomcNextMeeting;
  ratePoints?: FomcRatePoint[];
  probabilities?: FomcRateProbability[];
  latestStatement?: FomcStatement | null;
}) {
  if (!meeting.next_meeting) {
    return (
      <Card className="p-5">
        <p className="text-sm text-zinc-500 text-center">No upcoming FOMC meetings scheduled.</p>
      </Card>
    );
  }

  const days = meeting.days_until ?? 0;
  const latestRate = ratePoints && ratePoints.length > 0 ? ratePoints[ratePoints.length - 1] : null;
  const topProb = probabilities && probabilities.length > 0 ? probabilities[0] : null;
  const lastScore = latestStatement?.hawk_dove_score;

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between flex-wrap gap-4">
        {/* Left: next meeting + meta */}
        <div>
          <p className="text-xs font-semibold text-sky-600 dark:text-sky-500 uppercase tracking-wider mb-1">
            Next FOMC Meeting
          </p>
          <p className="text-lg font-bold text-zinc-900 dark:text-white">{formatDate(meeting.next_meeting)}</p>
          <div className="flex items-center gap-4 mt-1.5 flex-wrap">
            {latestRate && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                Current Rate:{" "}
                <span className="font-mono font-semibold text-zinc-800 dark:text-zinc-200">
                  {fmtRate(latestRate.rate_low, latestRate.rate_high)}
                </span>
              </span>
            )}
            {topProb && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                Market expects:{" "}
                <span className="font-mono font-semibold text-sky-600 dark:text-sky-400">
                  {fmtRate(topProb.target_rate_low, topProb.target_rate_high)}{" "}
                  ({topProb.probability.toFixed(0)}%)
                </span>
              </span>
            )}
          </div>
        </div>

        {/* Center: latest statement score */}
        {latestStatement && lastScore != null && (
          <div className="text-center">
            <p className="text-[10px] uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-0.5">
              Last Meeting ({formatDate(latestStatement.date)})
            </p>
            <div className={cn("flex items-center justify-center gap-1 text-sm font-semibold", scoreColor(lastScore))}>
              {lastScore >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              {scoreLabel(lastScore)}
              <span className="font-mono text-xs ml-1">
                ({lastScore >= 0 ? "+" : ""}{lastScore.toFixed(2)})
              </span>
            </div>
          </div>
        )}

        {/* Right: countdown */}
        <div className="text-right">
          <div className="flex items-center gap-1.5 text-zinc-500 dark:text-zinc-400">
            <Clock size={15} />
            <span className="text-sm">Countdown</span>
          </div>
          <p className="text-2xl font-bold font-mono text-zinc-900 dark:text-white mt-0.5">
            {days}
            <span className="text-sm font-normal text-zinc-500 ml-1">{days === 1 ? "day" : "days"}</span>
          </p>
        </div>
      </div>
    </Card>
  );
}
