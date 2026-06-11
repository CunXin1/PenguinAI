"use client";

import { useQuery } from "@tanstack/react-query";
import { Radio } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { StatusDot } from "./StatusDot";
import { admin } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import type { AdminDataSourceStatus } from "@/lib/types";

const DISPLAY_NAMES: Record<string, string> = {
  ibkr: "IBKR WebSocket",
  finnhub: "Finnhub WS",
  massive: "Massive Poller",
  close30m: "30m Bar Closer",
};

export function DataSourceStatus() {
  const { data, isLoading, isError, refetch } = useQuery<AdminDataSourceStatus>({
    queryKey: ["admin", "datasource-status"],
    queryFn: () => admin.datasourceStatus(),
    refetchInterval: 30_000,
  });

  if (isError) {
    return (
      <Card className="p-5">
        <p className="text-sm text-red-600 dark:text-red-400">Failed to load data source status</p>
        <button onClick={() => refetch()} className="text-xs text-sky-600 dark:text-sky-400 mt-2">Retry</button>
      </Card>
    );
  }

  if (isLoading || !data) {
    return (
      <Card className="p-5">
        <div className="h-6 w-48 bg-zinc-200 dark:bg-zinc-800 rounded animate-pulse" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-20 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse" />
          ))}
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Radio size={16} className="text-sky-500 dark:text-sky-400" />
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Data Sources</h2>
      </div>

      {/* Realtime sources */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {data.realtime.map((src) => (
          <div
            key={src.name}
            className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40 p-3 space-y-1.5"
          >
            <div className="flex items-center gap-2">
              <StatusDot status={src.alive ? "healthy" : "down"} />
              <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200">
                {DISPLAY_NAMES[src.name] ?? src.name}
              </span>
            </div>
            {src.uptime_s != null && (
              <p className="text-[10px] text-zinc-500">
                uptime {Math.floor(src.uptime_s / 3600)}h {Math.floor((src.uptime_s % 3600) / 60)}m
              </p>
            )}
            {src.restarts > 0 && (
              <p className="text-[10px] text-amber-600 dark:text-amber-400">{src.restarts} restarts</p>
            )}
          </div>
        ))}
      </div>

      {/* Fear & Greed scheduler health */}
      {data.fear_greed && (
        <div>
          <p className="text-[11px] text-zinc-500 uppercase tracking-wider mb-2">
            Fear &amp; Greed (CNN)
          </p>
          <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40 p-3 space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <StatusDot status={data.fear_greed.status} />
                <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200 capitalize">
                  {data.fear_greed.status}
                </span>
                <span className="text-[10px] text-zinc-500">
                  {data.fear_greed.source === "computed"
                    ? "VIX proxy (CNN down)"
                    : data.fear_greed.source === "cnn"
                      ? "live CNN"
                      : "—"}
                </span>
              </div>
              {data.fear_greed.score != null && (
                <span className="text-xs font-mono text-zinc-700 dark:text-zinc-300">
                  {Math.round(data.fear_greed.score)}
                  {data.fear_greed.rating ? ` · ${data.fear_greed.rating}` : ""}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-zinc-500">
              <span>
                last ok{" "}
                <span className="text-zinc-600 dark:text-zinc-400">
                  {data.fear_greed.last_success_at ? timeAgo(data.fear_greed.last_success_at) : "—"}
                </span>
              </span>
              {data.fear_greed.phase && (
                <span>
                  phase <span className="text-zinc-600 dark:text-zinc-400">{data.fear_greed.phase}</span>
                  {data.fear_greed.interval_min != null && ` · every ${data.fear_greed.interval_min}m`}
                </span>
              )}
              {data.fear_greed.next_run_at && (
                <span>
                  next <span className="text-zinc-600 dark:text-zinc-400">{timeAgo(data.fear_greed.next_run_at)}</span>
                </span>
              )}
              {data.fear_greed.consecutive_failures > 0 && (
                <span className="text-amber-600 dark:text-amber-400">
                  {data.fear_greed.consecutive_failures} consecutive failures
                </span>
              )}
            </div>
            {data.fear_greed.last_error && (
              <p className="text-[10px] text-red-500 dark:text-red-400">{data.fear_greed.last_error}</p>
            )}
          </div>
        </div>
      )}

      {/* Data freshness */}
      <div>
        <p className="text-[11px] text-zinc-500 uppercase tracking-wider mb-2">Data Freshness</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {data.freshness.map((f) => (
            <div
              key={f.table}
              className="flex items-center justify-between rounded border border-zinc-200 dark:border-zinc-800/50 px-2.5 py-1.5"
            >
              <span className="text-[11px] text-zinc-600 dark:text-zinc-400 font-mono">{f.table}</span>
              <span className="text-[10px] text-zinc-500">
                {f.latest_ts ? timeAgo(f.latest_ts) : "—"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Symbol coverage */}
      {data.coverage && Object.keys(data.coverage).length > 0 && (
        <div className="flex gap-4 text-[11px] text-zinc-500">
          {Object.entries(data.coverage).map(([key, val]) => (
            <span key={key}>
              <span className="text-zinc-700 dark:text-zinc-300 font-mono">{val}</span>{" "}
              {key.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}
