"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { fomc as fomcApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FomcScheduleItem } from "@/lib/types";

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr + "T12:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return dateStr;
  }
}

export function ScheduleTimeline() {
  const { data: schedule } = useQuery<FomcScheduleItem[]>({
    queryKey: ["fomcSchedule"],
    queryFn: () => fomcApi.schedule(10, 10),
    staleTime: 60 * 60 * 1000,
  });

  if (!schedule || schedule.length === 0) return null;

  const pastItems = schedule.filter((s) => s.past);
  const futureItems = schedule.filter((s) => !s.past);

  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-3">Meeting Schedule</h3>

      {futureItems.length > 0 && (
        <>
          <p className="text-[10px] uppercase tracking-wider text-sky-600 dark:text-sky-500 font-semibold mb-2">
            Upcoming
          </p>
          <div className="grid grid-cols-2 gap-1.5 mb-3">
            {futureItems.map((s, i) => (
              <div
                key={s.date}
                className={cn(
                  "px-2.5 py-1.5 rounded-lg text-center text-[11px] font-mono border",
                  i === 0
                    ? "border-sky-500/50 bg-sky-500/10 text-sky-700 dark:text-sky-400 font-semibold animate-pulse"
                    : "border-sky-500/20 bg-sky-500/5 text-sky-600 dark:text-sky-400/80",
                )}
              >
                {formatDate(s.date)}
              </div>
            ))}
          </div>
        </>
      )}

      {pastItems.length > 0 && (
        <>
          <p className="text-[10px] uppercase tracking-wider text-zinc-400 dark:text-zinc-500 font-semibold mb-2">
            Past
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            {pastItems.map((s) => (
              <div
                key={s.date}
                className="px-2.5 py-1.5 rounded-lg text-center text-[11px] font-mono border border-zinc-200 dark:border-zinc-800 text-zinc-400 dark:text-zinc-600"
              >
                {formatDate(s.date)}
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}
