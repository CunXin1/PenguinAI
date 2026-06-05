import { Activity, TrendingUp, TrendingDown, Landmark } from "lucide-react";
import { StatTile } from "@/components/ui/StatTile";
import { MOCK_MARKET } from "@/lib/mock";

/** Top-of-dashboard market snapshot strip. */
export function MarketPulse() {
  const m = MOCK_MARKET;
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <StatTile
        label="Market Sentiment"
        value={m.sentiment}
        sub={m.sentimentLabel}
        accent={m.sentiment >= 50 ? "up" : "down"}
        icon={<Activity size={16} />}
      />
      <StatTile
        label="Active Signals"
        value={m.activeSignals.toLocaleString()}
        sub={`${m.longCount} long · ${m.shortCount} short`}
        accent="brand"
        icon={<TrendingUp size={16} />}
      />
      <StatTile
        label="Advancers"
        value={m.advancers}
        sub={`vs ${m.decliners} decliners`}
        accent="up"
        icon={<TrendingUp size={16} />}
      />
      <StatTile
        label="FOMC Stance"
        value={m.fomcLabel}
        sub={`hawk–dove ${m.fomcScore}`}
        accent={m.fomcScore < 0 ? "up" : "down"}
        icon={m.fomcScore < 0 ? <TrendingUp size={16} /> : <Landmark size={16} />}
      />
    </div>
  );
}
