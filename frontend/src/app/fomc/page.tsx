"use client";

import { useQuery } from "@tanstack/react-query";
import { Landmark, Clock, ExternalLink, TrendingUp, TrendingDown } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FomcNextMeeting, FomcScheduleItem, FomcStatement, FomcTrendPoint } from "@/lib/types";

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

function scoreBg(score: number): string {
  if (score >= 0.3) return "bg-red-500";
  if (score >= 0.1) return "bg-orange-500";
  if (score > -0.1) return "bg-zinc-400 dark:bg-zinc-500";
  if (score > -0.3) return "bg-sky-500";
  return "bg-emerald-500";
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr + "T12:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return dateStr;
  }
}

function CountdownCard({ meeting }: { meeting: FomcNextMeeting }) {
  if (!meeting.next_meeting) {
    return (
      <Card className="p-5">
        <p className="text-sm text-zinc-500 text-center">No upcoming FOMC meetings scheduled.</p>
      </Card>
    );
  }

  const days = meeting.days_until ?? 0;
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold text-sky-600 dark:text-sky-400 uppercase tracking-wider mb-1">
            Next FOMC Meeting
          </p>
          <p className="text-lg font-bold text-zinc-900 dark:text-white">
            {formatDate(meeting.next_meeting)}
          </p>
        </div>
        <div className="text-right">
          <div className="flex items-center gap-1.5 text-zinc-600 dark:text-zinc-400">
            <Clock size={15} />
            <span className="text-sm">Countdown</span>
          </div>
          <p className="text-2xl font-bold font-mono text-zinc-900 dark:text-white mt-0.5">
            {days}
            <span className="text-sm font-normal text-zinc-500 ml-1">
              {days === 1 ? "day" : "days"}
            </span>
          </p>
        </div>
      </div>
    </Card>
  );
}

function TrendChart({ points }: { points: FomcTrendPoint[] }) {
  if (points.length === 0) {
    return (
      <Card className="p-5">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-3">
          Hawk/Dove Score Trend
        </h3>
        <p className="text-sm text-zinc-500 text-center py-6">
          No trend data available yet. FOMC statements will appear here once the scraper populates them.
        </p>
      </Card>
    );
  }

  const maxAbs = Math.max(0.5, ...points.map((p) => Math.abs(p.score)));

  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
        Hawk/Dove Score Trend
      </h3>
      <p className="text-[11px] text-zinc-500 mb-4">
        Positive = hawkish (tighter policy) · Negative = dovish (looser policy)
      </p>

      <div className="space-y-2">
        {/* Axis labels */}
        <div className="flex items-center justify-between text-[10px] text-zinc-400 px-1">
          <span>Dovish</span>
          <span>Neutral</span>
          <span>Hawkish</span>
        </div>

        {points.map((p) => {
          const pct = ((p.score / maxAbs) * 50 + 50);
          const isHawk = p.score >= 0;
          return (
            <div key={p.date} className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-zinc-500 w-20 shrink-0 text-right">
                {formatDate(p.date)}
              </span>
              <div className="flex-1 h-5 relative">
                <div className="absolute inset-0 bg-zinc-100 dark:bg-zinc-800 rounded" />
                <div className="absolute top-0 bottom-0 left-1/2 w-px bg-zinc-300 dark:bg-zinc-600" />
                <div
                  className={cn(
                    "absolute top-0.5 bottom-0.5 rounded",
                    isHawk ? "bg-red-500/70" : "bg-emerald-500/70",
                  )}
                  style={
                    isHawk
                      ? { left: "50%", width: `${(p.score / maxAbs) * 50}%` }
                      : { right: "50%", width: `${(-p.score / maxAbs) * 50}%` }
                  }
                />
              </div>
              <span className={cn("text-[10px] font-mono w-12 shrink-0", scoreColor(p.score))}>
                {p.score >= 0 ? "+" : ""}{p.score.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function ScheduleTimeline({ schedule }: { schedule: FomcScheduleItem[] }) {
  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-3">
        Meeting Schedule
      </h3>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
        {schedule.map((s) => (
          <div
            key={s.date}
            className={cn(
              "px-3 py-2 rounded-lg text-center text-xs font-mono border",
              s.past
                ? "border-zinc-200 dark:border-zinc-800 text-zinc-400 dark:text-zinc-600"
                : "border-sky-500/30 bg-sky-500/5 text-sky-600 dark:text-sky-400 font-semibold",
            )}
          >
            {formatDate(s.date)}
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function FomcPage() {
  const { data: nextMeeting } = useQuery<FomcNextMeeting>({
    queryKey: ["fomcNextMeeting"],
    queryFn: () => fomcApi.nextMeeting(),
    staleTime: 60 * 60 * 1000,
  });

  const { data: trend } = useQuery<FomcTrendPoint[]>({
    queryKey: ["fomcTrend"],
    queryFn: () => fomcApi.trend(20),
    staleTime: 60 * 60 * 1000,
  });

  const { data: statements, isLoading: statementsLoading } = useQuery<FomcStatement[]>({
    queryKey: ["fomcStatements"],
    queryFn: () => fomcApi.statements(50),
    staleTime: 60 * 60 * 1000,
  });

  const { data: schedule } = useQuery<FomcScheduleItem[]>({
    queryKey: ["fomcSchedule"],
    queryFn: () => fomcApi.schedule(),
    staleTime: 60 * 60 * 1000,
  });

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <Landmark size={20} className="text-sky-500 dark:text-sky-400" /> FOMC Watch
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          Federal Open Market Committee statements, hawk/dove analysis & meeting schedule
        </p>
      </div>

      {/* Next meeting countdown */}
      {nextMeeting && <CountdownCard meeting={nextMeeting} />}

      {/* Hawk/dove trend chart */}
      <TrendChart points={trend ?? []} />

      {/* Meeting schedule */}
      {schedule && schedule.length > 0 && <ScheduleTimeline schedule={schedule} />}

      {/* Past statements timeline */}
      <div>
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-3">
          Past Statements
        </h3>

        {statementsLoading && (
          <p className="text-sm text-zinc-400 dark:text-zinc-600 animate-pulse text-center py-6">
            Loading statements...
          </p>
        )}

        {!statementsLoading && (!statements || statements.length === 0) && (
          <Card className="p-5">
            <p className="text-sm text-zinc-500 text-center">
              No FOMC statements loaded yet. Run the FOMC scraper to populate historical data.
            </p>
          </Card>
        )}

        {statements && statements.length > 0 && (
          <div className="space-y-3">
            {statements.map((s) => (
              <Card key={s.date} className="p-4 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1.5 min-w-0">
                    <div className="flex items-center gap-2">
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
                          {s.hawk_dove_score >= 0
                            ? <TrendingUp size={11} />
                            : <TrendingDown size={11} />}
                          {scoreLabel(s.hawk_dove_score)}
                        </span>
                      )}
                    </div>
                    {s.summary && (
                      <p className="text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed">
                        {s.summary}
                      </p>
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
                  </div>
                  {s.hawk_dove_score !== null && (
                    <div className="shrink-0 text-right">
                      <div className={cn(
                        "text-lg font-bold font-mono",
                        scoreColor(s.hawk_dove_score),
                      )}>
                        {s.hawk_dove_score >= 0 ? "+" : ""}{s.hawk_dove_score.toFixed(2)}
                      </div>
                      <div className="text-[10px] text-zinc-500">score</div>
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
