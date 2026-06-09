"use client";

import { cn } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  healthy: "bg-emerald-500",
  degraded: "bg-amber-500",
  down: "bg-red-500",
  online: "bg-emerald-500",
  offline: "bg-red-500",
  unknown: "bg-zinc-400 dark:bg-zinc-500",
};

export function StatusDot({ status, className }: { status: string; className?: string }) {
  const color = STATUS_COLORS[status] ?? "bg-zinc-400 dark:bg-zinc-500";
  return (
    <span
      className={cn("inline-block h-2.5 w-2.5 rounded-full shrink-0", color, className)}
    />
  );
}
