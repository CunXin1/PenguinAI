"use client";

import { useQuery } from "@tanstack/react-query";
import { Brain } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { admin } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import type { AdminModelPerformance } from "@/lib/types";

export function ModelPerformance() {
  const { data, isLoading } = useQuery<AdminModelPerformance>({
    queryKey: ["admin", "model-performance"],
    queryFn: () => admin.modelPerformance(),
    refetchInterval: 300_000,
  });

  if (isLoading || !data) {
    return (
      <Card className="p-5">
        <div className="h-6 w-44 bg-zinc-800 rounded animate-pulse" />
        <div className="mt-4 space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-6 bg-zinc-800 rounded animate-pulse" />
          ))}
        </div>
      </Card>
    );
  }

  const maxImportance = Math.max(...Object.values(data.feature_importance), 0.01);
  const dist = data.signal_distribution;

  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Brain size={16} className="text-sky-400" />
        <h2 className="text-sm font-semibold text-zinc-200">Models</h2>
      </div>

      {/* Model files */}
      <div className="flex flex-wrap gap-3">
        {data.models.map((m) => (
          <div
            key={m.name}
            className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 flex-1 min-w-[140px]"
          >
            <p className="text-xs font-medium text-zinc-200">{m.name}</p>
            {m.exists ? (
              <>
                <p className="text-[10px] text-zinc-500 mt-1">{m.size_human}</p>
                {m.last_modified && (
                  <p className="text-[10px] text-zinc-500">trained {timeAgo(m.last_modified)}</p>
                )}
              </>
            ) : (
              <p className="text-[10px] text-red-400 mt-1">not found</p>
            )}
          </div>
        ))}
      </div>

      {/* Signal distribution */}
      <div>
        <p className="text-[11px] text-zinc-500 uppercase tracking-wider mb-2">
          Signal Distribution ({dist.total} cached)
        </p>
        <div className="flex gap-3">
          {Object.entries(dist.by_direction).map(([dir, count]) => (
            <div key={dir} className="flex items-center gap-1.5 text-[11px]">
              <span
                className={cn(
                  "px-1.5 py-0.5 rounded text-[10px] font-semibold border",
                  dir === "LONG"
                    ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
                    : dir === "SHORT"
                      ? "text-red-400 bg-red-500/10 border-red-500/30"
                      : "text-zinc-400 bg-zinc-800 border-zinc-700"
                )}
              >
                {dir}
              </span>
              <span className="text-zinc-400">{count}</span>
            </div>
          ))}
          {dist.avg_confidence != null && (
            <span className="text-zinc-500 ml-auto">
              avg conf: <span className="text-zinc-300">{(dist.avg_confidence * 100).toFixed(1)}%</span>
            </span>
          )}
        </div>
      </div>

      {/* Feature importance */}
      {Object.keys(data.feature_importance).length > 0 && (
        <div>
          <p className="text-[11px] text-zinc-500 uppercase tracking-wider mb-2">
            Feature Importance (Top {Object.keys(data.feature_importance).length})
          </p>
          <div className="space-y-1">
            {Object.entries(data.feature_importance).map(([name, val]) => (
              <div key={name} className="flex items-center gap-2">
                <span className="text-[10px] text-zinc-400 font-mono w-28 truncate shrink-0">
                  {name}
                </span>
                <div className="flex-1 h-3 rounded bg-zinc-800 overflow-hidden">
                  <div
                    className="h-full rounded bg-sky-500/60"
                    style={{ width: `${(val / maxImportance) * 100}%` }}
                  />
                </div>
                <span className="text-[10px] text-zinc-500 w-10 text-right">
                  {(val * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
