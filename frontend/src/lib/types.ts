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

// ── Symbol request (data-demand queue) ────────────────────────────────────────
export type SymbolRequestStatus =
  | "pending"
  | "real_pending_ingest"
  | "delisted"
  | "rejected_junk"
  | "ingested"
  | "already_covered";

export interface SymbolRequestResult {
  symbol: string;
  status: SymbolRequestStatus;
  request_count: number;
  message: string;
}

/** Error thrown by `apiFetch` — carries the HTTP status and parsed body. */
export interface ApiError extends Error {
  status?: number;
  data?: {
    detail?: string;
    reason?: "not_in_universe" | "delisted";
    ticker?: string;
    [k: string]: unknown;
  };
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
  username: string | null;
  display_name: string | null;
  tier: UserTier;
  email_verified: boolean;
  oauth_provider: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface RegisterResponse {
  message: string;
  email: string;
}

// ── Chat assistant ──────────────────────────────────────────────────────────────
export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

/** Per-user quota snapshot. limit/remaining of 0/-1 mean "unlimited". */
export interface ChatQuota {
  tier: UserTier;
  limit: number; // messages per window; 0 = unlimited
  remaining: number; // remaining this window; -1 = unlimited
  reset_seconds: number; // until the window resets
  window_seconds: number; // window length
}

export interface ChatReply {
  reply: string;
  usage: ChatQuota;
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
  _computing?: boolean; // true while awaiting on-demand signal computation
}

/** Raw shape returned by GET /api/news/market and /api/news/{ticker}. */
export interface NewsApiArticle {
  id: string;
  headline: string;
  summary: string;
  source: string;
  url?: string;
  image?: string;
  datetime: number; // unix timestamp (seconds)
  tickers?: string[];
  category?: string;
  sentiment?: "positive" | "negative" | "neutral" | null;
  sentiment_score?: number | null;
}

export interface NewsArticle {
  id: string;
  headline: string;
  summary: string;
  body?: string; // full article text, paragraphs separated by "\n\n"
  source: string;
  url?: string; // link to original article (from Finnhub)
  image?: string; // thumbnail URL (from Finnhub)
  datetime?: number; // unix timestamp from API
  time: string; // display string, e.g. "2h ago" — computed from datetime or mock
  sentiment: "positive" | "negative" | "neutral";
  tickers?: string[];
  category?: string; // general/forex/crypto/merger
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

/** User-facing chart ranges (shared PriceChart). Default is 1W. */
export type ChartRange = "1D" | "1W" | "1M" | "3M" | "1Y";

/** A latest-quote board row (live price + same-session % change). */
export interface Quote {
  ticker: string;
  price: number;
  change_pct: number;
  time?: string; // ISO timestamp of the latest bar
}

/** One cell of the homepage index strip — quote + a downsampled intraday spark. */
export interface MiniQuote {
  ticker: string;
  price: number;
  change_pct: number;
  time?: string;
  spark: number[]; // session closes (5-min buckets) for the thumbnail
}

// ── Market heatmap (market-cap treemap) ──────────────────────────────────────
/** One tile of the market-cap heatmap. */
export interface HeatmapTile {
  ticker: string;
  name: string | null;
  sector: string | null;
  market_cap: number;
  price: number;
  change_pct: number;
}

/** Selectable performance window for the market map. */
export type HeatmapPeriod = "1D" | "1W" | "1M" | "3M" | "1Y";

/** An index ETF tile (SPY/QQQ/DIA/IWM) shown above the map. */
export interface IndexTile {
  ticker: string;
  label: string;
  price: number;
  change_pct: number;
}

export interface HeatmapResponse {
  market_open: boolean;
  as_of: string; // ISO timestamp
  period: HeatmapPeriod;
  count: number;
  items: HeatmapTile[];
  indices: IndexTile[];
}

// ── Market status (global open / closed) ──────────────────────────────────────
export type SessionPhase = "PRE_MARKET" | "REGULAR" | "AFTER_HOURS" | "OVERNIGHT" | "CLOSED";

export interface MarketStatus {
  market_open: boolean; // backward compat: regular session OR ticks advancing
  market_active: boolean; // true during ANY session (pre/regular/after/overnight)
  session_phase: SessionPhase;
  session_open: boolean; // true only during the ET regular session (09:30–16:00)
  source: string;
  as_of: string;
  latest_tick: string | null;
}

// ── Celebrity Holdings ───────────────────────────────────────────────────────
export type CelebAction = "BUY" | "SELL" | "HOLD";
export type CelebSourceType = "13F" | "daily_disclosure";

export interface CelebrityHolding {
  id: string;
  reported_at: string;
  celebrity: string;
  ticker: string;
  ticker_name: string;
  action: CelebAction;
  shares: number | null;
  value_usd: number | null;
  source_type: CelebSourceType;
  filing_url: string | null;
}

export interface CelebritySummary {
  celebrity: string;
  total_trades: number;
  buys: number;
  sells: number;
  latest_trade: string;
}

export interface CelebrityTopHolding {
  ticker: string;
  ticker_name: string;
  latest_action: CelebAction;
  last_activity: string;
  shares: number | null;
  value_usd: number | null;
  trade_count: number;
}

// ── Earnings ──────────────────────────────────────────────────────────────────
// ── FOMC ─────────────────────────────────────────────────────────────────────
export interface FomcStatement {
  date: string;
  datetime: number;
  hawk_dove_score: number | null;
  summary: string | null;
  document_url: string | null;
}

export interface FomcTrendPoint {
  date: string;
  score: number;
}

export interface FomcNextMeeting {
  next_meeting: string | null;
  days_until: number | null;
}

export interface FomcScheduleItem {
  date: string;
  past: boolean;
}

export interface FomcRatePoint {
  date: string;
  rate_low: number;
  rate_high: number;
}

export interface FomcMarketReaction {
  date: string;
  spy_return_pct: number | null;
  spy_close: number | null;
  rate_low: number | null;
  rate_high: number | null;
}

export interface FomcRateProbability {
  meeting_date: string | null;
  target_rate_low: number;
  target_rate_high: number;
  probability: number;
}

export interface FomcDiffLine {
  type: "added" | "removed" | "unchanged";
  text: string;
}

export interface FomcDiffResult {
  current_date: string;
  previous_date: string | null;
  diff: FomcDiffLine[];
}

// ── Fear & Greed Index + Volatility (VIX/VVIX) ───────────────────────────────
export type FearGreedRating =
  | "extreme fear"
  | "fear"
  | "neutral"
  | "greed"
  | "extreme greed";

export interface FearGreedComponent {
  key: string;
  label: string;
  score: number | null; // 0–100 normalized contribution
  rating: string | null;
}

export interface FearGreedCurrent {
  score: number | null; // 0–100
  rating: string | null; // raw CNN rating
  label: string | null; // display label, e.g. "Extreme Fear"
  updated_at: string | null;
  source: string | null; // "cnn" | "computed" (VIX proxy fallback)
  previous: {
    close?: number | null;
    week?: number | null;
    month?: number | null;
    year?: number | null;
  };
  components: FearGreedComponent[];
}

export interface FearGreedHistoryPoint {
  date: string; // ISO date
  score: number;
  rating: string;
}

/** One daily bar of a volatility index (VIX/VVIX). time = unix seconds. */
export interface VolatilityBar {
  time: number;
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
}

export interface VolatilitySeries {
  symbol: string; // VIX | VVIX
  latest: number | null;
  change_pct: number | null;
  bars: VolatilityBar[];
}

// ── Admin Dashboard ─────────────────────────────────────────────────────────
export type ServiceStatus = "healthy" | "degraded" | "down";
export type OverallHealth = "healthy" | "degraded" | "critical";

export interface ServiceHealthItem {
  name: string;
  status: ServiceStatus;
  latency_ms: number | null;
  detail: string;
}

export interface SystemHealthOverview {
  overall: OverallHealth;
  checked_at: string;
  services: ServiceHealthItem[];
}

export interface ConnectionPool {
  pool_size: number;
  checked_in: number;
  checked_out: number;
  overflow: number;
  max_overflow: number;
}

export interface TableStat {
  name: string;
  approx_rows: number;
  size_bytes: number;
  size_human: string;
  latest_ts: string | null;
}

export interface DatabaseHealth {
  connection_pool: ConnectionPool;
  active_connections: number;
  tables: TableStat[];
  total_db_size_bytes: number;
  total_db_size_human: string;
}

export interface RouteInfo {
  method: string;
  path: string;
  name: string | null;
}

export interface ProbeResult {
  endpoint: string;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
}

export interface EndpointHealth {
  routes: RouteInfo[];
  probes: ProbeResult[];
}

export interface TaskRunInfo {
  name: string;
  task: string;
  schedule: string;
  last_run: string | null;
  last_status: string | null;
  last_duration_s: number | null;
}

export interface QueueDepth {
  name: string;
  pending: number;
}

export interface WorkerInfo {
  name: string;
  status: string;
  active_tasks: number;
  processed: number;
  concurrency: number;
  queues: string[];
}

export interface AdminTaskStatus {
  scheduled_tasks: TaskRunInfo[];
  queues: QueueDepth[];
  workers: WorkerInfo[];
}

export interface RealtimeSourceStatus {
  name: string;
  alive: boolean;
  uptime_s: number | null;
  restarts: number;
  detail: string;
}

export interface DataFreshness {
  table: string;
  latest_ts: string | null;
}

export interface AdminDataSourceStatus {
  realtime: RealtimeSourceStatus[];
  freshness: DataFreshness[];
  coverage: Record<string, number>;
}

export interface ModelFileInfo {
  name: string;
  file_path: string;
  exists: boolean;
  size_bytes: number | null;
  size_human: string | null;
  last_modified: string | null;
}

export interface SignalDistribution {
  total: number;
  by_direction: Record<string, number>;
  avg_confidence: number | null;
}

export interface AdminModelPerformance {
  models: ModelFileInfo[];
  feature_importance: Record<string, number>;
  signal_distribution: SignalDistribution;
}

export interface AdminUserStats {
  total: number;
  by_tier: Record<string, number>;
  verified: number;
  active: number;
  registered_today: number;
  registered_this_week: number;
}

export interface AdminUserRow {
  id: string;
  email: string;
  display_name: string | null;
  tier: string;
  is_active: boolean;
  email_verified: boolean;
  created_at: string | null;
}

export interface AdminUserListResponse {
  users: AdminUserRow[];
  total: number;
  page: number;
  per_page: number;
}

export interface ActionResponse {
  triggered: boolean;
  task_id: string | null;
  task_name: string;
}

export interface TaskResultResponse {
  task_id: string;
  status: string;
  result: string | null;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
}

export interface LogsResponse {
  entries: LogEntry[];
  total_buffered: number;
  showing: number;
  min_level: string;
}

/** Reporting session — backend derives it from `earnings.report_hour` (Finnhub `hour`). */
export type EarningsSession = "BMO" | "AMC" | "TBD";

/** One row of the `earnings` table (+ display-only joins). */
export interface EarningsEvent {
  ticker: string;
  report_date: string; // ISO date, e.g. "2026-06-08"
  /** Lifecycle phase (backend-computed, single source of truth for upcoming→past).
   *  REPORTED = actuals in · UPCOMING = future, no actuals · PENDING = date passed, awaiting actuals. */
  status?: "REPORTED" | "UPCOMING" | "PENDING";
  fiscal_quarter: number | null; // 1–4
  fiscal_year: number | null;    // e.g. 2026
  eps_actual: number | null;
  eps_estimate: number | null;
  eps_surprise_pct: number | null;
  revenue_actual: number | null; // absolute USD
  revenue_estimate: number | null;
  revenue_surprise_pct: number | null;
  guidance_text: string | null;
  // ── enriched server-side ──
  name?: string;
  session?: EarningsSession;
  /** Post-earnings gap: reaction day open vs prev close (%) */
  reaction_open_pct: number | null;
  /** Post-earnings 1-day: reaction day close vs prev close (%) */
  reaction_close_pct: number | null;
  /** Why a reaction is / isn't shown (reported rows only): available = computed ·
   *  pending = post-report session not closed yet (fills next day) · unavailable = no price source. */
  reaction_status?: "available" | "pending" | "unavailable" | null;
}
