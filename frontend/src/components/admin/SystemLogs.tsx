"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScrollText, RefreshCw } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { admin } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { LogsResponse } from "@/lib/types";

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "text-zinc-600",
  INFO: "text-zinc-400",
  WARNING: "text-amber-400",
  ERROR: "text-red-400",
  CRITICAL: "text-red-500 font-bold",
};

export function SystemLogs() {
  const [level, setLevel] = useState("INFO");
  const [autoRefresh, setAutoRefresh] = useState(false);

  const { data, isLoading, refetch } = useQuery<LogsResponse>({
    queryKey: ["admin", "logs", level],
    queryFn: () => admin.logs(200, level),
    refetchInterval: autoRefresh ? 10_000 : false,
  });

  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-center gap-2">
        <ScrollText size={16} className="text-sky-400" />
        <h2 className="text-sm font-semibold text-zinc-200">System Logs</h2>
        <span className="ml-auto text-[11px] text-zinc-500">
          {data ? `${data.showing}/${data.total_buffered}` : "—"}
        </span>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        {LEVELS.map((l) => (
          <button
            key={l}
            onClick={() => setLevel(l)}
            className={cn(
              "px-2 py-1 rounded text-[10px] font-semibold border transition-colors",
              level === l
                ? "bg-zinc-800 text-zinc-200 border-zinc-600"
                : "text-zinc-500 border-zinc-800 hover:text-zinc-300"
            )}
          >
            {l}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={cn(
              "px-2 py-1 rounded text-[10px] border transition-colors",
              autoRefresh
                ? "text-sky-400 border-sky-500/30 bg-sky-500/10"
                : "text-zinc-500 border-zinc-800"
            )}
          >
            Auto
          </button>
          <button
            onClick={() => refetch()}
            className="p-1 rounded text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {/* Log entries */}
      <div className="max-h-80 overflow-y-auto rounded-lg bg-zinc-950 border border-zinc-800 p-3 font-mono text-[10px] leading-relaxed space-y-0.5">
        {isLoading && <p className="text-zinc-600">Loading...</p>}
        {data?.entries.length === 0 && (
          <p className="text-zinc-600">No log entries at {level} level</p>
        )}
        {data?.entries.map((entry, i) => (
          <div key={i} className="flex gap-2 hover:bg-zinc-900/50">
            <span className="text-zinc-600 shrink-0 w-20">
              {new Date(entry.timestamp).toLocaleTimeString()}
            </span>
            <span className={cn("shrink-0 w-16", LEVEL_COLORS[entry.level] ?? "text-zinc-400")}>
              {entry.level}
            </span>
            <span className="text-zinc-600 shrink-0 w-24 truncate">{entry.logger}</span>
            <span className="text-zinc-300 break-all">{entry.message}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
