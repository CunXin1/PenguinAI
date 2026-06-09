"use client";

import { Clock } from "lucide-react";
import { Card } from "@/components/ui/Card";
import type { FomcNextMeeting, FomcRatePoint, FomcRateProbability } from "@/lib/types";

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

export function CountdownCard({
  meeting,
  ratePoints,
  probabilities,
}: {
  meeting: FomcNextMeeting;
  ratePoints?: FomcRatePoint[];
  probabilities?: FomcRateProbability[];
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

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <p className="text-xs font-semibold text-sky-500 uppercase tracking-wider mb-1">
            Next FOMC Meeting
          </p>
          <p className="text-lg font-bold text-white">{formatDate(meeting.next_meeting)}</p>
          <div className="flex items-center gap-4 mt-1.5">
            {latestRate && (
              <span className="text-xs text-zinc-400">
                Current Rate:{" "}
                <span className="font-mono font-semibold text-zinc-200">
                  {fmtRate(latestRate.rate_low, latestRate.rate_high)}
                </span>
              </span>
            )}
            {topProb && (
              <span className="text-xs text-zinc-400">
                Market expects:{" "}
                <span className="font-mono font-semibold text-sky-400">
                  {fmtRate(topProb.target_rate_low, topProb.target_rate_high)}{" "}
                  ({topProb.probability.toFixed(0)}%)
                </span>
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="flex items-center gap-1.5 text-zinc-400">
            <Clock size={15} />
            <span className="text-sm">Countdown</span>
          </div>
          <p className="text-2xl font-bold font-mono text-white mt-0.5">
            {days}
            <span className="text-sm font-normal text-zinc-500 ml-1">{days === 1 ? "day" : "days"}</span>
          </p>
        </div>
      </div>
    </Card>
  );
}
