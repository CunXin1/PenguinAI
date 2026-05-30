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
