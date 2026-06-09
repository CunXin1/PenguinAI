"use client";

import { useQuery } from "@tanstack/react-query";
import { ListChecks } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { StatusDot } from "./StatusDot";
import { admin } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import type { AdminTaskStatus } from "@/lib/types";

const STATUS_BADGE: Record<string, string> = {
  SUCCESS: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  FAILURE: "text-red-400 bg-red-500/10 border-red-500/30",
  RUNNING: "text-sky-400 bg-sky-500/10 border-sky-500/30",
};

export function TaskStatus() {
  const { data, isLoading } = useQuery<AdminTaskStatus>({
    queryKey: ["admin", "task-status"],
    queryFn: () => admin.taskStatus(),
    refetchInterval: 15_000,
  });

  if (isLoading || !data) {
    return (
      <Card className="p-5">
        <div className="h-6 w-40 bg-zinc-800 rounded animate-pulse" />
        <div className="mt-4 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-8 bg-zinc-800 rounded animate-pulse" />
          ))}
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-center gap-2">
        <ListChecks size={16} className="text-sky-400" />
        <h2 className="text-sm font-semibold text-zinc-200">Tasks & Workers</h2>
      </div>

      {/* Queue depths */}
      <div className="flex gap-3">
        {data.queues.map((q) => (
          <div
            key={q.name}
            className="flex-1 rounded-lg border border-zinc-800 bg-zinc-900/40 p-2.5 text-center"
          >
            <p className="text-lg font-bold font-mono text-zinc-200">{q.pending}</p>
            <p className="text-[10px] text-zinc-500 uppercase tracking-wider">{q.name} queue</p>
          </div>
        ))}
      </div>

      {/* Workers */}
      {data.workers.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {data.workers.map((w) => (
            <div
              key={w.name}
              className="flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900/40 px-2.5 py-1.5 text-[11px]"
            >
              <StatusDot status={w.status} />
              <span className="text-zinc-300 font-mono">{w.name.split("@").pop()}</span>
              <span className="text-zinc-600">·</span>
              <span className="text-zinc-500">{w.active_tasks} active</span>
            </div>
          ))}
        </div>
      )}

      {/* Scheduled tasks table */}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="text-left py-1.5 font-medium">Task</th>
              <th className="text-left py-1.5 font-medium">Schedule</th>
              <th className="text-right py-1.5 font-medium">Last Run</th>
              <th className="text-right py-1.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.scheduled_tasks.map((t) => (
              <tr key={t.name} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                <td className="py-1.5 text-zinc-300 font-mono">{t.name}</td>
                <td className="py-1.5 text-zinc-500">{t.schedule}</td>
                <td className="py-1.5 text-right text-zinc-400">
                  {t.last_run ? timeAgo(t.last_run) : "—"}
                </td>
                <td className="py-1.5 text-right">
                  {t.last_status ? (
                    <span
                      className={cn(
                        "px-1.5 py-0.5 rounded text-[10px] font-semibold border",
                        STATUS_BADGE[t.last_status] ?? "text-zinc-400 bg-zinc-800 border-zinc-700"
                      )}
                    >
                      {t.last_status}
                    </span>
                  ) : (
                    <span className="text-zinc-600">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
