"use client";

import { MarketPulse } from "@/components/dashboard/MarketPulse";
import { MarketChart } from "@/components/dashboard/MarketChart";
import { TopSignals } from "@/components/dashboard/TopSignals";
import { TrendingTickers } from "@/components/dashboard/TrendingTickers";
import { NewsPreview } from "@/components/dashboard/NewsPreview";
import { WatchlistWidget } from "@/components/dashboard/WatchlistWidget";

export default function DashboardPage() {
  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white">Market Dashboard</h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          AI-generated Long / Short signals across US equities · updated continuously
        </p>
      </div>

      <MarketPulse />

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <MarketChart />
          <TopSignals />
        </div>
        <div className="space-y-6">
          <TrendingTickers />
          <NewsPreview />
          <WatchlistWidget />
        </div>
      </div>
    </div>
  );
}
