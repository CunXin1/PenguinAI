"use client";

import { PriceChart } from "@/components/charts/PriceChart";

/**
 * Dashboard market chart — the shared PriceChart pinned to QQQ. Range/series
 * switching, live polling and the demo fallback all live in PriceChart so this
 * stays a thin wrapper.
 */
export function MarketChart() {
  return <PriceChart ticker="QQQ" subtitle="Invesco QQQ Trust" defaultRange="1W" />;
}
