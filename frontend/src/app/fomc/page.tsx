"use client";

import { useQuery } from "@tanstack/react-query";
import { Landmark } from "lucide-react";
import { fomc as fomcApi } from "@/lib/api";
import type { FomcNextMeeting, FomcRatePoint, FomcRateProbability, FomcStatement } from "@/lib/types";

import { CountdownCard } from "@/components/fomc/CountdownCard";
import { RateChart } from "@/components/fomc/RateChart";
import { TrendAndReactionRow } from "@/components/fomc/TrendAndReactionPanel";
import { FedWatchCard } from "@/components/fomc/FedWatchCard";
import { StatementList } from "@/components/fomc/StatementList";
import { ScheduleTimeline } from "@/components/fomc/ScheduleTimeline";
import { FomcNewsCard } from "@/components/fomc/FomcNewsCard";

export default function FomcPage() {
  const { data: nextMeeting } = useQuery<FomcNextMeeting>({
    queryKey: ["fomcNextMeeting"],
    queryFn: () => fomcApi.nextMeeting(),
    staleTime: 60 * 60 * 1000,
  });

  const { data: ratePoints } = useQuery<FomcRatePoint[]>({
    queryKey: ["fomcRateHistory", 5],
    queryFn: () => fomcApi.rateHistory(5),
    staleTime: 60 * 60 * 1000,
  });

  const { data: probabilities } = useQuery<FomcRateProbability[]>({
    queryKey: ["fomcRateProbabilities"],
    queryFn: () => fomcApi.rateProbabilities(),
    staleTime: 30 * 60 * 1000,
  });

  const { data: latestStatements } = useQuery<FomcStatement[]>({
    queryKey: ["fomcLatestStatement"],
    queryFn: () => fomcApi.statements(1),
    staleTime: 60 * 60 * 1000,
  });

  const latestStatement = latestStatements?.[0] ?? null;

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <Landmark size={20} className="text-sky-600 dark:text-sky-400" /> FOMC Watch
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          Federal Open Market Committee — rate history, hawk/dove analysis, market impact & Fed news
        </p>
      </div>

      {nextMeeting && (
        <CountdownCard
          meeting={nextMeeting}
          ratePoints={ratePoints}
          probabilities={probabilities}
          latestStatement={latestStatement}
        />
      )}

      {/* Rate chart full width */}
      <RateChart />

      {/* Hawk/Dove + SPY Reaction side by side, shared count selector */}
      <TrendAndReactionRow />

      {/* FedWatch */}
      <FedWatchCard />

      {/* Bottom: statements (2/3) + sidebar (1/3) */}
      <div className="grid lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-5">
          <StatementList />
        </div>
        <div className="space-y-5">
          <ScheduleTimeline />
          <FomcNewsCard />
        </div>
      </div>
    </div>
  );
}
