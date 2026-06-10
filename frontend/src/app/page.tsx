"use client";

import { MarketIndices } from "@/components/dashboard/MarketIndices";
import { MarketChart } from "@/components/dashboard/MarketChart";
import { TopSignals } from "@/components/dashboard/TopSignals";
import { TrendingTickers } from "@/components/dashboard/TrendingTickers";
import { NewsPreview } from "@/components/dashboard/NewsPreview";
import { WatchlistWidget } from "@/components/dashboard/WatchlistWidget";
import { FomcWidget } from "@/components/dashboard/FomcWidget";
import { FearGreedWidget } from "@/components/dashboard/FearGreedWidget";

export default function DashboardPage() {
  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white">Market Dashboard</h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          AI-generated Long / Short signals across US equities · updated continuously
        </p>
      </div>

      <MarketIndices />

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <MarketChart />
          <TopSignals />
        </div>
        <div className="space-y-4 lg:space-y-6">
          <div className="grid sm:grid-cols-2 lg:grid-cols-1 gap-4 lg:gap-6">
            <TrendingTickers />
            <WatchlistWidget />
          </div>
          <FearGreedWidget />
          <FomcWidget />
          <NewsPreview />
        </div>
      </div>
    </div>
  );
}
