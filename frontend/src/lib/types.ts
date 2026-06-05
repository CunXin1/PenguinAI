// ── Signal types ──────────────────────────────────────────────────────────────
export type Direction = "LONG" | "SHORT" | "NEUTRAL";
export type HoldingPeriod = "INTRADAY" | "SHORT_TERM" | "SWING" | "POSITION";
export type UserTier = "FREE" | "PRO" | "PREMIUM" | "ADMIN";

export interface MLScores {
  xgb_prob_up: number | null;
  rf_prob_up: number | null;
  ensemble_prob: number | null;
}

export interface SentimentInfo {
  finbert_score: number | null;
  post_count: number | null;
  hawk_dove_ref: number | null;
}

export interface Signal {
  ticker: string;
  direction: Direction;
  confidence: number;          // 0.0 – 1.0
  holding_period: HoldingPeriod;
  ml_scores: MLScores;
  sentiment: SentimentInfo;
  ai_attribution: string | null;
  ai_analysis: string | null;
  tier_required: UserTier;
  computed_at: string;         // ISO timestamp
  expires_at: string;
}

export interface SignalListItem {
  ticker: string;
  direction: Direction;
  confidence: number;
  holding_period: HoldingPeriod;
  computed_at: string;
}

// ── Ticker types ──────────────────────────────────────────────────────────────
export interface Ticker {
  ticker: string;
  name: string;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  tags: string[];
  is_active: boolean;
}

export interface TickerSearchResult {
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
}

// ── Candle types (TradingView Lightweight Charts) ─────────────────────────────
export interface Candle {
  time: string;   // ISO or Unix timestamp
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── User types ─────────────────────────────────────────────────────────────────
export interface User {
  id: string;
  email: string;
  display_name: string | null;
  tier: UserTier;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

// ── Watchlist ─────────────────────────────────────────────────────────────────
export interface WatchlistItem {
  ticker: string;
  signal: SignalListItem | null;
}

// ── Dashboard / display view-models ───────────────────────────────────────────
/** A signal enriched with display-only fields (price, change, sparkline). */
export interface SignalView extends SignalListItem {
  name?: string;
  price?: number;
  change_pct?: number; // raw percent, e.g. 2.4 → +2.4%
  spark?: number[];
}

export interface NewsArticle {
  id: string;
  headline: string;
  summary: string;
  body?: string; // full article text, paragraphs separated by "\n\n"
  source: string;
  time: string; // display string, e.g. "2h ago"
  sentiment: "positive" | "negative" | "neutral";
  tickers?: string[];
}

export interface TrendingTicker {
  ticker: string;
  price: number;
  change_pct: number;
  spark: number[];
}

export interface MarketStats {
  sentiment: number; // 0–100
  sentimentLabel: string;
  activeSignals: number;
  longCount: number;
  shortCount: number;
  advancers: number;
  decliners: number;
  fomcScore: number; // -1..1, positive = hawkish
  fomcLabel: string;
}

export interface ProfileUser {
  display_name: string;
  email: string;
  tier: UserTier;
  member_since: string;
  watchlist_count: number;
  signals_viewed: number;
  win_rate: number;
}

/** A row in the screener / stock universe. */
export interface UniverseRow {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  change_pct: number;
  direction: Direction;
  confidence: number;
}

/** One OHLC bar for the candlestick chart (time = unix seconds). */
export interface CandleBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

/** A latest-quote board row (live price + same-session % change). */
export interface Quote {
  ticker: string;
  price: number;
  change_pct: number;
  time?: string; // ISO timestamp of the latest bar
}
