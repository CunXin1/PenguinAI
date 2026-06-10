"use client";

import { Card } from "@/components/ui/Card";
import type { FearGreedComponent } from "@/lib/types";
import { fgColor } from "./util";

function titleCase(s: string | null): string {
  if (!s) return "—";
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

function Row({ c }: { c: FearGreedComponent }) {
  const score = c.score ?? null;
  const color = score != null ? fgColor(score) : "#71717a";
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-zinc-700 dark:text-zinc-300 font-medium">{c.label}</span>
        <span className="font-medium" style={{ color }}>
          {titleCase(c.rating)}
        </span>
      </div>
      {/* 0–100 track with a marker at the component score */}
      <div className="relative h-1.5 rounded-full bg-zinc-200 dark:bg-zinc-800">
        {score != null && (
          <div
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full border-2 border-white dark:border-zinc-950"
            style={{ left: `${score}%`, backgroundColor: color }}
            title={`${Math.round(score)}/100`}
          />
        )}
      </div>
    </div>
  );
}

export function ComponentBreakdown({
  components,
}: {
  components: FearGreedComponent[];
}) {
  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
        What Drives the Index
      </h3>
      <p className="text-[11px] text-zinc-500 mb-4">
        Seven equal-weighted market indicators · marker = current reading (left = fear, right = greed)
      </p>
      {components.length === 0 ? (
        <p className="text-sm text-zinc-400 dark:text-zinc-600 py-4 text-center">
          Component breakdown unavailable.
        </p>
      ) : (
        <div className="space-y-4">
          {components.map((c) => (
            <Row key={c.key} c={c} />
          ))}
        </div>
      )}
    </Card>
  );
}
