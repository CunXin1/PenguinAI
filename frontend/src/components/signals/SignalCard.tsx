"use client";

import type { Signal } from "@/lib/types";

interface Props {
  signal: Signal;
}

const DIRECTION_STYLE: Record<string, string> = {
  LONG:    "text-emerald-400 border-emerald-500/40 bg-emerald-500/10",
  SHORT:   "text-red-400    border-red-500/40    bg-red-500/10",
  NEUTRAL: "text-zinc-400   border-zinc-600       bg-zinc-800/50",
};

const PERIOD_LABEL: Record<string, string> = {
  INTRADAY:   "Intraday",
  SHORT_TERM: "1–3 Days",
  SWING:      "1–2 Weeks",
  POSITION:   "1+ Month",
};

export function SignalCard({ signal }: Props) {
  const dirStyle = DIRECTION_STYLE[signal.direction] ?? DIRECTION_STYLE.NEUTRAL;
  const confidencePct = Math.round(signal.confidence * 100);

  return (
    <div className="rounded-xl border border-zinc-700/60 bg-zinc-900 p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <span className="text-2xl font-bold text-white tracking-wide">{signal.ticker}</span>
          <span className="ml-3 text-xs text-zinc-500 font-mono">
            {PERIOD_LABEL[signal.holding_period]}
          </span>
        </div>
        <span className={`px-3 py-1 rounded-full text-sm font-semibold border ${dirStyle}`}>
          {signal.direction}
        </span>
      </div>

      {/* Confidence meter */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-zinc-500">
          <span>Confidence</span>
          <span className="font-mono text-white">{confidencePct}%</span>
        </div>
        <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${
              signal.direction === "LONG"  ? "bg-emerald-500" :
              signal.direction === "SHORT" ? "bg-red-500"     : "bg-zinc-600"
            }`}
            style={{ width: `${confidencePct}%` }}
          />
        </div>
      </div>

      {/* ML Scores */}
      {signal.ml_scores && (
        <div className="grid grid-cols-3 gap-2 text-center">
          <ScorePill label="XGBoost" value={signal.ml_scores.xgb_prob_up} />
          <ScorePill label="Random Forest" value={signal.ml_scores.rf_prob_up} />
          <ScorePill label="Ensemble" value={signal.ml_scores.ensemble_prob} highlight />
        </div>
      )}

      {/* Sentiment */}
      {signal.sentiment?.finbert_score !== null && (
        <div className="flex items-center gap-3 text-xs text-zinc-400">
          <span>Sentiment</span>
          <span className={`font-mono font-medium ${
            (signal.sentiment.finbert_score ?? 0) > 0.1  ? "text-emerald-400" :
            (signal.sentiment.finbert_score ?? 0) < -0.1 ? "text-red-400"     : "text-zinc-400"
          }`}>
            {((signal.sentiment.finbert_score ?? 0) * 100).toFixed(1)}
          </span>
          <span className="text-zinc-600">·</span>
          <span>{signal.sentiment.post_count} posts</span>
        </div>
      )}

      {/* AI Attribution */}
      {signal.ai_attribution && (
        <div className="rounded-lg bg-zinc-800/60 border border-zinc-700/40 px-3 py-2">
          <p className="text-xs text-zinc-500 mb-1 font-medium uppercase tracking-wider">Key Drivers</p>
          <p className="text-sm text-zinc-300 leading-relaxed">{signal.ai_attribution}</p>
        </div>
      )}

      {/* AI Analysis */}
      {signal.ai_analysis && (
        <div className="rounded-lg bg-zinc-800/40 border border-zinc-700/30 px-3 py-2">
          <p className="text-xs text-zinc-500 mb-1 font-medium uppercase tracking-wider">AI Analysis</p>
          <p className="text-sm text-zinc-300 leading-relaxed">{signal.ai_analysis}</p>
        </div>
      )}

      {/* Timestamp */}
      <p className="text-xs text-zinc-600 font-mono">
        Computed {new Date(signal.computed_at).toLocaleTimeString()}
      </p>
    </div>
  );
}

function ScorePill({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: number | null;
  highlight?: boolean;
}) {
  if (value === null) return null;
  const pct = Math.round(value * 100);
  return (
    <div className={`rounded-lg px-2 py-1.5 ${highlight ? "bg-zinc-700/60 border border-zinc-600" : "bg-zinc-800"}`}>
      <p className="text-[10px] text-zinc-500 truncate">{label}</p>
      <p className={`text-sm font-bold font-mono ${pct >= 55 ? "text-emerald-400" : pct <= 45 ? "text-red-400" : "text-zinc-300"}`}>
        {pct}%
      </p>
    </div>
  );
}
