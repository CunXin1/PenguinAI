import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Card } from "./Card";

type Accent = "up" | "down" | "neutral" | "brand";

const ACCENT: Record<Accent, string> = {
  up: "text-emerald-400",
  down: "text-red-400",
  neutral: "text-zinc-200",
  brand: "text-sky-400",
};

export function StatTile({
  label,
  value,
  sub,
  accent = "neutral",
  icon,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: Accent;
  icon?: ReactNode;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] text-zinc-500 uppercase tracking-wider">{label}</p>
        {icon && <span className="text-zinc-600">{icon}</span>}
      </div>
      <p className={cn("text-2xl font-bold font-mono mt-1.5 leading-none", ACCENT[accent])}>{value}</p>
      {sub && <p className="text-xs text-zinc-500 mt-1.5">{sub}</p>}
    </Card>
  );
}
