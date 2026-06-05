import Link from "next/link";
import { Flame } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Sparkline } from "@/components/ui/Sparkline";
import { MOCK_TRENDING } from "@/lib/mock";
import { signedPct, money } from "@/lib/utils";

export function TrendingTickers() {
  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold text-zinc-300 flex items-center gap-2 mb-3">
        <Flame size={15} className="text-orange-400" />
        Trending
      </h3>
      <div className="space-y-0.5">
        {MOCK_TRENDING.map((t) => {
          const up = t.change_pct >= 0;
          return (
            <Link
              key={t.ticker}
              href={`/signals/${t.ticker}`}
              className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-zinc-800/50 transition-colors"
            >
              <span className="font-mono font-semibold text-sm text-zinc-200 w-14 shrink-0">{t.ticker}</span>
              <Sparkline data={t.spark} color={up ? "#34d399" : "#f87171"} width={72} className="flex-1" />
              <span className="font-mono text-xs text-zinc-400 w-16 text-right shrink-0">{money(t.price)}</span>
              <span className={`font-mono text-xs w-14 text-right shrink-0 ${up ? "text-emerald-400" : "text-red-400"}`}>
                {signedPct(t.change_pct, 1)}
              </span>
            </Link>
          );
        })}
      </div>
    </Card>
  );
}
