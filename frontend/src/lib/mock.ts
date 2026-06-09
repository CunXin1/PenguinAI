/**
 * Demo / fallback data for pages that may not yet have a live backend.
 * Keep this minimal — only data that has no real API backing yet.
 */
import type {
  Signal,
  Direction,
  HoldingPeriod,
  ProfileUser,
  UniverseRow,
} from "./types";

export const MOCK_USER: ProfileUser = {
  display_name: "Demo Trader",
  email: "you@penguinai.io",
  tier: "PRO",
  member_since: "Jan 2026",
  watchlist_count: 12,
  signals_viewed: 348,
  win_rate: 63,
};

// Used by mockSignalDetail() to resolve ticker metadata for the detail-page fallback.
const MOCK_UNIVERSE: UniverseRow[] = [
  { ticker: "NVDA", name: "NVIDIA Corp.", sector: "Technology", price: 1182.4, change_pct: 2.4, direction: "LONG", confidence: 0.87 },
  { ticker: "AAPL", name: "Apple Inc.", sector: "Technology", price: 214.3, change_pct: 0.8, direction: "LONG", confidence: 0.72 },
  { ticker: "MSFT", name: "Microsoft Corp.", sector: "Technology", price: 452.1, change_pct: 1.2, direction: "LONG", confidence: 0.69 },
  { ticker: "AMD", name: "Advanced Micro Devices", sector: "Technology", price: 158.9, change_pct: -1.8, direction: "SHORT", confidence: 0.64 },
  { ticker: "AVGO", name: "Broadcom Inc.", sector: "Technology", price: 1421.0, change_pct: 2.0, direction: "LONG", confidence: 0.76 },
  { ticker: "PLTR", name: "Palantir Technologies", sector: "Technology", price: 28.6, change_pct: 4.2, direction: "LONG", confidence: 0.84 },
  { ticker: "MU", name: "Micron Technology", sector: "Technology", price: 142.3, change_pct: 1.5, direction: "LONG", confidence: 0.61 },
  { ticker: "QCOM", name: "Qualcomm Inc.", sector: "Technology", price: 172.8, change_pct: -0.6, direction: "NEUTRAL", confidence: 0.53 },
  { ticker: "META", name: "Meta Platforms", sector: "Communication", price: 512.4, change_pct: 1.9, direction: "LONG", confidence: 0.78 },
  { ticker: "GOOGL", name: "Alphabet Inc.", sector: "Communication", price: 178.1, change_pct: 0.2, direction: "NEUTRAL", confidence: 0.55 },
  { ticker: "NFLX", name: "Netflix Inc.", sector: "Communication", price: 645.2, change_pct: -0.3, direction: "NEUTRAL", confidence: 0.52 },
  { ticker: "AMZN", name: "Amazon.com Inc.", sector: "Consumer", price: 186.3, change_pct: 1.1, direction: "LONG", confidence: 0.71 },
  { ticker: "TSLA", name: "Tesla Inc.", sector: "Consumer", price: 176.2, change_pct: -3.1, direction: "SHORT", confidence: 0.81 },
  { ticker: "COST", name: "Costco Wholesale", sector: "Consumer", price: 842.5, change_pct: 0.4, direction: "LONG", confidence: 0.58 },
  { ticker: "WMT", name: "Walmart Inc.", sector: "Consumer", price: 67.9, change_pct: 0.6, direction: "LONG", confidence: 0.6 },
  { ticker: "JPM", name: "JPMorgan Chase", sector: "Financials", price: 198.4, change_pct: -0.4, direction: "NEUTRAL", confidence: 0.54 },
  { ticker: "V", name: "Visa Inc.", sector: "Financials", price: 275.6, change_pct: 0.7, direction: "LONG", confidence: 0.62 },
  { ticker: "GS", name: "Goldman Sachs", sector: "Financials", price: 452.8, change_pct: 1.0, direction: "LONG", confidence: 0.59 },
  { ticker: "COIN", name: "Coinbase Global", sector: "Financials", price: 235.1, change_pct: -2.6, direction: "SHORT", confidence: 0.67 },
  { ticker: "LLY", name: "Eli Lilly & Co.", sector: "Healthcare", price: 842.1, change_pct: 1.3, direction: "LONG", confidence: 0.66 },
  { ticker: "UNH", name: "UnitedHealth Group", sector: "Healthcare", price: 512.3, change_pct: -1.1, direction: "SHORT", confidence: 0.57 },
  { ticker: "XOM", name: "Exxon Mobil", sector: "Energy", price: 112.4, change_pct: -0.8, direction: "NEUTRAL", confidence: 0.51 },
  { ticker: "CVX", name: "Chevron Corp.", sector: "Energy", price: 156.7, change_pct: -0.5, direction: "NEUTRAL", confidence: 0.5 },
  { ticker: "SPY", name: "SPDR S&P 500 ETF", sector: "ETF", price: 543.2, change_pct: 0.3, direction: "LONG", confidence: 0.56 },
  { ticker: "QQQ", name: "Invesco QQQ ETF", sector: "ETF", price: 472.8, change_pct: 0.9, direction: "LONG", confidence: 0.63 },
  { ticker: "IWM", name: "iShares Russell 2000 ETF", sector: "ETF", price: 218.4, change_pct: -0.5, direction: "NEUTRAL", confidence: 0.52 },
  { ticker: "DIA", name: "SPDR Dow Jones ETF", sector: "ETF", price: 432.1, change_pct: 0.1, direction: "NEUTRAL", confidence: 0.5 },
  { ticker: "BAC", name: "Bank of America", sector: "Financials", price: 42.6, change_pct: -0.7, direction: "NEUTRAL", confidence: 0.53 },
  { ticker: "ORCL", name: "Oracle Corp.", sector: "Technology", price: 188.9, change_pct: 1.4, direction: "LONG", confidence: 0.64 },
  { ticker: "CRM", name: "Salesforce Inc.", sector: "Technology", price: 276.3, change_pct: 0.6, direction: "LONG", confidence: 0.58 },
];

const r2 = (n: number) => Math.round(n * 100) / 100;
const r4 = (n: number) => Math.round(n * 10000) / 10000;

const HOLDING_BY_DIR: Record<Direction, HoldingPeriod> = {
  LONG: "SWING",
  SHORT: "SHORT_TERM",
  NEUTRAL: "INTRADAY",
};

/** A full demo Signal for the detail-page fallback when backend times out. */
export function mockSignalDetail(ticker: string): Signal {
  const u = MOCK_UNIVERSE.find((x) => x.ticker === ticker);
  const direction: Direction = u?.direction ?? "NEUTRAL";
  const confidence = u?.confidence ?? 0.5;
  const bias = direction === "LONG" ? 0.18 : direction === "SHORT" ? -0.18 : 0;
  const clamp = (x: number) => Math.max(0.03, Math.min(0.97, x));
  const xgb = clamp(0.5 + bias + (confidence - 0.5) * 0.4);
  const rf = clamp(0.5 + bias * 0.8 + (confidence - 0.5) * 0.3);
  const ensemble = clamp(xgb * 0.6 + rf * 0.4);
  const finbert = direction === "LONG" ? 0.32 : direction === "SHORT" ? -0.28 : 0.04;

  const analysis =
    direction === "LONG"
      ? `${ticker} shows upward momentum: the ML ensemble leans bullish and recent news flow is constructive.`
      : direction === "SHORT"
        ? `${ticker} faces downside pressure as models skew bearish amid softening sentiment.`
        : `${ticker} is range-bound — model probabilities sit near a coin flip with mixed sentiment.`;

  return {
    ticker,
    direction,
    confidence,
    holding_period: HOLDING_BY_DIR[direction],
    ml_scores: { xgb_prob_up: r4(xgb), rf_prob_up: r4(rf), ensemble_prob: r4(ensemble) },
    sentiment: { finbert_score: r2(finbert), post_count: 40 + ((ticker.length * 37) % 160), hawk_dove_ref: -0.2 },
    ai_attribution: `${ensemble >= 0.5 ? "Bullish" : "Bearish"} ML ensemble (${Math.round(ensemble * 100)}%) · ${direction === "NEUTRAL" ? "mixed" : direction === "LONG" ? "positive" : "weak"} social sentiment`,
    ai_analysis: `${analysis} Macro backdrop is mildly dovish.`,
    tier_required: "FREE",
    computed_at: "2026-06-05T14:30:00Z",
    expires_at: "2026-06-05T18:30:00Z",
  };
}
