"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { StatusDot } from "./StatusDot";
import { admin } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SystemHealthOverview } from "@/lib/types";

const BANNER: Record<string, { bg: string; text: string; label: string }> = {
  healthy: {
    bg: "bg-emerald-500/10 border-emerald-500/30",
    text: "text-emerald-400",
    label: "All Systems Operational",
  },
  degraded: {
    bg: "bg-amber-500/10 border-amber-500/30",
    text: "text-amber-400",
    label: "Degraded Performance",
  },
  critical: {
    bg: "bg-red-500/10 border-red-500/30",
    text: "text-red-400",
    label: "Critical — Action Required",
  },
};

const DISPLAY_NAMES: Record<string, string> = {
  timescaledb: "TimescaleDB",
  redis: "Redis",
  backend_api: "Backend API",
  celery_workers: "Celery Workers",
  realtime_supervisor: "RT Supervisor",
  ibkr_stream: "IBKR Stream",
  finnhub_stream: "Finnhub WS",
};

export function HealthOverview() {
  const { data, isLoading, isError } = useQuery<SystemHealthOverview>({
    queryKey: ["admin", "health-overview"],
    queryFn: () => admin.healthOverview(),
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return (
      <Card className="p-5">
        <div className="h-8 w-48 bg-zinc-800 rounded animate-pulse" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-16 bg-zinc-800 rounded-lg animate-pulse" />
          ))}
        </div>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card className="p-5 border-red-500/30">
        <p className="text-red-400 text-sm">Failed to load system health</p>
      </Card>
    );
  }

  const banner = BANNER[data.overall] ?? BANNER.critical;

  return (
    <Card className="p-5 space-y-4">
      <div className={cn("rounded-lg border px-4 py-3 flex items-center gap-3", banner.bg)}>
        <Activity size={18} className={banner.text} />
        <span className={cn("font-semibold text-sm", banner.text)}>{banner.label}</span>
        <span className="ml-auto text-[11px] text-zinc-500">
          {new Date(data.checked_at).toLocaleTimeString()}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {data.services.map((svc) => (
          <div
            key={svc.name}
            className="flex items-start gap-2.5 rounded-lg border border-zinc-800 bg-zinc-900/40 p-3"
          >
            <StatusDot status={svc.status} className="mt-1" />
            <div className="min-w-0">
              <p className="text-xs font-medium text-zinc-200 truncate">
                {DISPLAY_NAMES[svc.name] ?? svc.name}
              </p>
              <p className="text-[11px] text-zinc-500 truncate mt-0.5">{svc.detail}</p>
              {svc.latency_ms != null && (
                <p className="text-[10px] text-zinc-600 mt-0.5">{svc.latency_ms}ms</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
