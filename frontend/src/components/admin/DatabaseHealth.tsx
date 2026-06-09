"use client";

import { useQuery } from "@tanstack/react-query";
import { Database } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { admin } from "@/lib/api";
import { cn, compact, timeAgo } from "@/lib/utils";
import type { DatabaseHealth as DBHealthType } from "@/lib/types";

export function DatabaseHealth() {
  const { data, isLoading } = useQuery<DBHealthType>({
    queryKey: ["admin", "db-health"],
    queryFn: () => admin.dbHealth(),
    refetchInterval: 60_000,
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

  const pool = data.connection_pool;
  const used = pool.checked_out;
  const total = pool.pool_size + pool.max_overflow;
  const pct = total > 0 ? (used / total) * 100 : 0;

  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Database size={16} className="text-sky-400" />
        <h2 className="text-sm font-semibold text-zinc-200">Database</h2>
        <span className="ml-auto text-[11px] text-zinc-500">{data.total_db_size_human}</span>
      </div>

      {/* Connection pool bar */}
      <div>
        <div className="flex items-center justify-between text-[11px] text-zinc-500 mb-1">
          <span>Connection Pool</span>
          <span>{used}/{total} used</span>
        </div>
        <div className="h-2 rounded-full bg-zinc-800 overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              pct > 80 ? "bg-red-500" : pct > 60 ? "bg-amber-500" : "bg-emerald-500"
            )}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
        <p className="text-[10px] text-zinc-600 mt-1">
          {data.active_connections} active pg connections
        </p>
      </div>

      {/* Table stats */}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800">
              <th className="text-left py-1.5 font-medium">Table</th>
              <th className="text-right py-1.5 font-medium">Rows</th>
              <th className="text-right py-1.5 font-medium">Size</th>
              <th className="text-right py-1.5 font-medium">Freshness</th>
            </tr>
          </thead>
          <tbody>
            {data.tables.map((t) => (
              <tr key={t.name} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                <td className="py-1.5 text-zinc-300 font-mono">{t.name}</td>
                <td className="py-1.5 text-right text-zinc-400">{compact(t.approx_rows)}</td>
                <td className="py-1.5 text-right text-zinc-400">{t.size_human}</td>
                <td className="py-1.5 text-right">
                  {t.latest_ts ? (
                    <span className="text-zinc-400">{timeAgo(t.latest_ts)}</span>
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
