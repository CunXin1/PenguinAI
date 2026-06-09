"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Globe, ChevronDown, ChevronUp } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { admin } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { EndpointHealth as EndpointHealthType } from "@/lib/types";

export function EndpointHealth() {
  const [expanded, setExpanded] = useState(false);

  const { data, isLoading } = useQuery<EndpointHealthType>({
    queryKey: ["admin", "endpoint-health"],
    queryFn: () => admin.healthEndpoints(),
    refetchInterval: 60_000,
  });

  if (isLoading || !data) {
    return (
      <Card className="p-5">
        <div className="h-6 w-40 bg-zinc-800 rounded animate-pulse" />
        <div className="mt-4 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-8 bg-zinc-800 rounded animate-pulse" />
          ))}
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Globe size={16} className="text-sky-400" />
        <h2 className="text-sm font-semibold text-zinc-200">API Endpoints</h2>
        <span className="ml-auto text-[11px] text-zinc-500">{data.routes.length} routes</span>
      </div>

      {/* Probes */}
      <div className="space-y-1.5">
        {data.probes.map((p) => (
          <div
            key={p.endpoint}
            className="flex items-center gap-2 rounded border border-zinc-800/50 px-2.5 py-1.5"
          >
            <span
              className={cn(
                "inline-block h-2 w-2 rounded-full shrink-0",
                p.status_code && p.status_code < 400
                  ? "bg-emerald-500"
                  : p.status_code && p.status_code < 500
                    ? "bg-amber-500"
                    : "bg-red-500"
              )}
            />
            <span className="text-[11px] text-zinc-300 font-mono flex-1 truncate">
              {p.endpoint}
            </span>
            {p.status_code && (
              <span
                className={cn(
                  "text-[10px] font-mono",
                  p.status_code < 400 ? "text-emerald-400" : "text-red-400"
                )}
              >
                {p.status_code}
              </span>
            )}
            {p.latency_ms != null && (
              <span className="text-[10px] text-zinc-500">{p.latency_ms}ms</span>
            )}
            {p.error && (
              <span className="text-[10px] text-red-400 truncate max-w-[120px]">{p.error}</span>
            )}
          </div>
        ))}
      </div>

      {/* Route list (expandable) */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
      >
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        {expanded ? "Hide" : "Show"} all routes
      </button>

      {expanded && (
        <div className="max-h-60 overflow-y-auto space-y-0.5">
          {data.routes.map((r, i) => (
            <div
              key={`${r.method}-${r.path}-${i}`}
              className="flex items-center gap-2 text-[10px] font-mono"
            >
              <span
                className={cn(
                  "w-12 text-right shrink-0 font-semibold",
                  r.method === "GET"
                    ? "text-emerald-400"
                    : r.method === "POST"
                      ? "text-sky-400"
                      : r.method === "PATCH"
                        ? "text-amber-400"
                        : r.method === "DELETE"
                          ? "text-red-400"
                          : "text-zinc-400"
                )}
              >
                {r.method}
              </span>
              <span className="text-zinc-400 truncate">{r.path}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
