"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Landmark, Clock, ExternalLink, TrendingUp, TrendingDown, GitCompareArrows } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  FomcDiffResult,
  FomcMarketReaction,
  FomcNextMeeting,
  FomcRatePoint,
  FomcScheduleItem,
  FomcStatement,
  FomcTrendPoint,
} from "@/lib/types";

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

function fmtRate(low: number, high: number): string {
  if (low === high) return `${low.toFixed(2)}%`;
  return `${low.toFixed(2)}–${high.toFixed(2)}%`;
}

/* ── Countdown ─────────────────────────────────────────────────────────────── */
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
          <p className="text-lg font-bold text-zinc-900 dark:text-white">{formatDate(meeting.next_meeting)}</p>
        </div>
        <div className="text-right">
          <div className="flex items-center gap-1.5 text-zinc-600 dark:text-zinc-400">
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

/* ── Fed Funds Rate Chart ──────────────────────────────────────────────────── */
function RateChart({ points }: { points: FomcRatePoint[] }) {
  if (points.length === 0) return null;

  const maxRate = Math.max(...points.map((p) => p.rate_high));
  const chartH = 160;

  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
        Federal Funds Rate
      </h3>
      <p className="text-[11px] text-zinc-500 mb-3">
        Target range (lower–upper) at each FOMC meeting · Source: Federal Reserve (cross-verified)
      </p>

      <div className="relative" style={{ height: chartH }}>
        {/* Y axis labels */}
        {[0, 1, 2, 3, 4, 5, 6].filter((v) => v <= maxRate + 0.5).map((v) => {
          const y = chartH - (v / (maxRate + 0.5)) * chartH;
          return (
            <div key={v} className="absolute left-0 flex items-center" style={{ top: y - 6 }}>
              <span className="text-[9px] font-mono text-zinc-400 w-7 text-right">{v}%</span>
              <div
                className="absolute left-8 h-px bg-zinc-200 dark:bg-zinc-800"
                style={{ width: "calc(100% - 2rem)", right: 0 }}
              />
            </div>
          );
        })}

        {/* Rate line */}
        <svg
          viewBox={`0 0 ${points.length} ${chartH}`}
          preserveAspectRatio="none"
          className="absolute left-8 top-0 right-0 bottom-0 w-[calc(100%-2rem)]"
          style={{ height: chartH }}
        >
          {/* Shaded band between low and high */}
          <path
            d={
              points
                .map((p, i) => {
                  const yHigh = chartH - (p.rate_high / (maxRate + 0.5)) * chartH;
                  return `${i === 0 ? "M" : "L"} ${i} ${yHigh}`;
                })
                .join(" ") +
              " " +
              points
                .map((p, i) => {
                  const yLow = chartH - (p.rate_low / (maxRate + 0.5)) * chartH;
                  return `L ${points.length - 1 - i} ${yLow}`;
                })
                .reverse()
                .join(" ") +
              " Z"
            }
            fill="rgba(56, 189, 248, 0.15)"
          />
          {/* Upper line */}
          <polyline
            points={points
              .map((p, i) => `${i},${chartH - (p.rate_high / (maxRate + 0.5)) * chartH}`)
              .join(" ")}
            fill="none"
            stroke="rgb(56, 189, 248)"
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>

      {/* X axis */}
      <div className="flex justify-between ml-8 mt-1">
        <span className="text-[9px] font-mono text-zinc-400">{points[0]?.date.slice(0, 4)}</span>
        <span className="text-[9px] font-mono text-zinc-400">{points[points.length - 1]?.date.slice(0, 4)}</span>
      </div>

      {/* Current rate */}
      {points.length > 0 && (
        <div className="mt-3 text-center">
          <span className="text-xs text-zinc-500">Current: </span>
          <span className="text-sm font-semibold font-mono text-sky-500">
            {fmtRate(points[points.length - 1].rate_low, points[points.length - 1].rate_high)}
          </span>
        </div>
      )}
    </Card>
  );
}

/* ── Market Reaction ───────────────────────────────────────────────────────── */
function MarketReactionTable({ reactions }: { reactions: FomcMarketReaction[] }) {
  if (reactions.length === 0) return null;

  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
        SPY Market Reaction on FOMC Days
      </h3>
      <p className="text-[11px] text-zinc-500 mb-3">
        Close-to-close return on statement release day · Source: bars_1d (SPY)
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-200 dark:border-zinc-800">
              <th className="text-left py-1.5 font-medium text-zinc-500">Date</th>
              <th className="text-right py-1.5 font-medium text-zinc-500">Rate</th>
              <th className="text-right py-1.5 font-medium text-zinc-500">SPY Close</th>
              <th className="text-right py-1.5 font-medium text-zinc-500">Return</th>
              <th className="text-left py-1.5 font-medium text-zinc-500 pl-3 w-32">Impact</th>
            </tr>
          </thead>
          <tbody>
            {reactions.map((r) => {
              const ret = r.spy_return_pct;
              const isPos = ret !== null && ret >= 0;
              const barWidth = ret !== null ? Math.min(Math.abs(ret) * 30, 100) : 0;
              return (
                <tr key={r.date} className="border-b border-zinc-100 dark:border-zinc-800/50">
                  <td className="py-1.5 font-mono text-zinc-700 dark:text-zinc-300">
                    {formatDate(r.date)}
                  </td>
                  <td className="py-1.5 text-right font-mono text-zinc-500">
                    {r.rate_low != null && r.rate_high != null ? fmtRate(r.rate_low, r.rate_high) : "—"}
                  </td>
                  <td className="py-1.5 text-right font-mono text-zinc-500">
                    {r.spy_close != null ? `$${r.spy_close.toFixed(2)}` : "—"}
                  </td>
                  <td className={cn(
                    "py-1.5 text-right font-mono font-semibold",
                    ret === null ? "text-zinc-400" : isPos ? "text-emerald-500" : "text-red-500",
                  )}>
                    {ret !== null ? `${isPos ? "+" : ""}${ret.toFixed(2)}%` : "—"}
                  </td>
                  <td className="py-1.5 pl-3">
                    {ret !== null && (
                      <div className="flex items-center gap-1">
                        <div
                          className={cn(
                            "h-2 rounded-sm",
                            isPos ? "bg-emerald-500/60" : "bg-red-500/60",
                          )}
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ── Hawk/Dove Trend ───────────────────────────────────────────────────────── */
function TrendChart({ points }: { points: FomcTrendPoint[] }) {
  if (points.length === 0) return null;
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
        <div className="flex items-center justify-between text-[10px] text-zinc-400 px-1">
          <span>Dovish</span>
          <span>Neutral</span>
          <span>Hawkish</span>
        </div>
        {points.map((p) => {
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

/* ── Statement Diff ────────────────────────────────────────────────────────── */
function StatementDiff({ date }: { date: string }) {
  const { data: diff, isLoading } = useQuery<FomcDiffResult>({
    queryKey: ["fomcDiff", date],
    queryFn: () => fomcApi.diff(date),
    staleTime: 60 * 60 * 1000,
  });

  if (isLoading) {
    return <p className="text-xs text-zinc-400 animate-pulse py-2">Loading diff...</p>;
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
              line.type === "unchanged" && "text-zinc-500 dark:text-zinc-500",
            )}
          >
            {line.text}{" "}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ── Schedule Timeline ─────────────────────────────────────────────────────── */
function ScheduleTimeline({ schedule }: { schedule: FomcScheduleItem[] }) {
  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-3">Meeting Schedule</h3>
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

/* ── Page ───────────────────────────────────────────────────────────────────── */
export default function FomcPage() {
  const [diffDate, setDiffDate] = useState<string | null>(null);

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

  const { data: rateHistory } = useQuery<FomcRatePoint[]>({
    queryKey: ["fomcRateHistory"],
    queryFn: () => fomcApi.rateHistory(),
    staleTime: 60 * 60 * 1000,
  });

  const { data: marketReaction } = useQuery<FomcMarketReaction[]>({
    queryKey: ["fomcMarketReaction"],
    queryFn: () => fomcApi.marketReaction(30),
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
          Federal Open Market Committee statements, hawk/dove analysis, rate history & market impact
        </p>
      </div>

      {nextMeeting && <CountdownCard meeting={nextMeeting} />}

      {/* Rate + Trend side by side on desktop */}
      <div className="grid md:grid-cols-2 gap-5">
        <RateChart points={rateHistory ?? []} />
        <TrendChart points={trend ?? []} />
      </div>

      {/* Market reaction */}
      {marketReaction && marketReaction.length > 0 && (
        <MarketReactionTable reactions={marketReaction} />
      )}

      {schedule && schedule.length > 0 && <ScheduleTimeline schedule={schedule} />}

      {/* Past statements with diff toggle */}
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
          </div>
        )}
      </div>
    </div>
  );
}
