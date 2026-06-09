/**
 * Demo data for the UI while the backend / data pipeline is not yet populated.
 * Components prefer the live API and fall back to these constants, so the pages
 * always look alive. All values are static (deterministic) to avoid SSR
 * hydration mismatches.
 */
import type {
  Signal,
  Direction,
  HoldingPeriod,
  SignalView,
  NewsArticle,
  TrendingTicker,
  MarketStats,
  ProfileUser,
  UniverseRow,
  EarningsEvent,
  CelebrityHolding,
  CelebritySummary,
} from "./types";

const NOW = "2026-06-05T14:30:00Z";

export const MOCK_SIGNALS: SignalView[] = [
  { ticker: "NVDA", name: "NVIDIA Corp.", direction: "LONG", confidence: 0.87, holding_period: "SWING", computed_at: NOW, price: 1182.4, change_pct: 2.4, spark: [1120, 1138, 1129, 1151, 1147, 1166, 1174, 1182] },
  { ticker: "PLTR", name: "Palantir Technologies", direction: "LONG", confidence: 0.84, holding_period: "POSITION", computed_at: NOW, price: 28.6, change_pct: 4.2, spark: [27.1, 27.4, 27.2, 27.9, 28.1, 28.0, 28.4, 28.6] },
  { ticker: "TSLA", name: "Tesla Inc.", direction: "SHORT", confidence: 0.81, holding_period: "SHORT_TERM", computed_at: NOW, price: 176.2, change_pct: -3.1, spark: [188, 185, 186, 182, 180, 179, 177, 176.2] },
  { ticker: "META", name: "Meta Platforms", direction: "LONG", confidence: 0.78, holding_period: "SWING", computed_at: NOW, price: 512.4, change_pct: 1.9, spark: [498, 503, 500, 507, 505, 510, 509, 512.4] },
  { ticker: "AVGO", name: "Broadcom Inc.", direction: "LONG", confidence: 0.76, holding_period: "POSITION", computed_at: NOW, price: 1421.0, change_pct: 2.0, spark: [1385, 1398, 1392, 1405, 1410, 1408, 1416, 1421] },
  { ticker: "AAPL", name: "Apple Inc.", direction: "LONG", confidence: 0.72, holding_period: "SWING", computed_at: NOW, price: 214.3, change_pct: 0.8, spark: [211.5, 212.4, 211.9, 213.1, 212.8, 213.6, 214.0, 214.3] },
  { ticker: "AMZN", name: "Amazon.com Inc.", direction: "LONG", confidence: 0.71, holding_period: "SWING", computed_at: NOW, price: 186.3, change_pct: 1.1, spark: [183.2, 184.1, 183.6, 185.0, 184.7, 185.6, 186.0, 186.3] },
  { ticker: "MSFT", name: "Microsoft Corp.", direction: "LONG", confidence: 0.69, holding_period: "POSITION", computed_at: NOW, price: 452.1, change_pct: 1.2, spark: [446, 449, 447, 450, 449, 451, 451.5, 452.1] },
  { ticker: "COIN", name: "Coinbase Global", direction: "SHORT", confidence: 0.67, holding_period: "SHORT_TERM", computed_at: NOW, price: 235.1, change_pct: -2.6, spark: [246, 243, 244, 240, 239, 238, 236, 235.1] },
  { ticker: "AMD", name: "Advanced Micro Devices", direction: "SHORT", confidence: 0.64, holding_period: "SHORT_TERM", computed_at: NOW, price: 158.9, change_pct: -1.8, spark: [164, 162, 163, 161, 160, 159.5, 159, 158.9] },
  { ticker: "GOOGL", name: "Alphabet Inc.", direction: "NEUTRAL", confidence: 0.55, holding_period: "SHORT_TERM", computed_at: NOW, price: 178.1, change_pct: 0.2, spark: [177.6, 178.2, 177.4, 178.0, 177.8, 178.3, 177.9, 178.1] },
  { ticker: "NFLX", name: "Netflix Inc.", direction: "NEUTRAL", confidence: 0.52, holding_period: "INTRADAY", computed_at: NOW, price: 645.2, change_pct: -0.3, spark: [647, 645, 648, 644, 646, 645.5, 646, 645.2] },
];

export const MOCK_TRENDING: TrendingTicker[] = [
  { ticker: "SMCI", price: 48.2, change_pct: 6.8, spark: [44, 45, 44.5, 46, 47, 46.5, 47.8, 48.2] },
  { ticker: "MSTR", price: 1680, change_pct: 5.1, spark: [1590, 1610, 1600, 1640, 1655, 1648, 1672, 1680] },
  { ticker: "GME", price: 24.1, change_pct: -7.2, spark: [26, 25.6, 25.8, 25, 24.6, 24.4, 24.2, 24.1] },
  { ticker: "SOFI", price: 9.85, change_pct: 3.4, spark: [9.5, 9.6, 9.55, 9.7, 9.72, 9.78, 9.8, 9.85] },
  { ticker: "RIVN", price: 13.2, change_pct: -4.1, spark: [13.8, 13.7, 13.75, 13.5, 13.4, 13.35, 13.25, 13.2] },
];

export const MOCK_NEWS: NewsArticle[] = [
  {
    id: "n1",
    headline: "Nvidia unveils next-gen Rubin AI accelerators, lifts full-year guidance",
    summary: "The chipmaker said data-center demand remains 'well ahead of supply,' with hyperscalers pre-committing to the new architecture through 2027.",
    body: "Nvidia used its developer conference to detail the Rubin platform, the successor to Blackwell, claiming a roughly 3x improvement in training throughput per watt. Management said initial shipments are already committed through the first half of next year.\n\nThe company raised its full-year outlook, citing 'durable, multi-year' demand from cloud providers building out generative-AI capacity. Several analysts called the guidance conservative given the visible order backlog and supply commitments from foundry partners.",
    source: "Reuters",
    time: "2h ago",
    sentiment: "positive",
    tickers: ["NVDA"],
  },
  {
    id: "n2",
    headline: "Tesla Q2 deliveries miss estimates as EV demand cools in Europe",
    summary: "Deliveries came in below consensus, renewing concerns over pricing power and margin compression heading into the second half.",
    body: "Tesla reported second-quarter deliveries that fell short of Wall Street expectations, with the shortfall concentrated in Europe where purchase incentives have been rolled back and competition from local EV makers has intensified.\n\nThe miss reignited debate over whether further price cuts will be needed to defend volume, a move that would pressure already-thin automotive margins. The company reaffirmed its full-year delivery target but offered no fresh detail on the lower-cost model.",
    source: "Bloomberg",
    time: "4h ago",
    sentiment: "negative",
    tickers: ["TSLA"],
  },
  {
    id: "n3",
    headline: "Palantir lands $480M defense contract; shares jump in premarket",
    summary: "The multi-year award expands the company's footprint across allied military logistics and battlefield analytics.",
    body: "Palantir secured a multi-year contract valued at up to $480 million to expand deployment of its AI platform across allied defense logistics networks. The award builds on a string of government wins this year.\n\nShares rose more than 6% in premarket trading. Executives have repeatedly pointed to government demand as the most visible part of the company's pipeline, even as commercial bookings accelerate.",
    source: "CNBC",
    time: "5h ago",
    sentiment: "positive",
    tickers: ["PLTR"],
  },
  {
    id: "n4",
    headline: "Fed minutes signal patience on rate cuts amid mixed inflation data",
    summary: "Officials remain divided, with several favoring holding rates steady until disinflation is 'more firmly established.'",
    body: "Minutes from the latest Federal Reserve meeting showed policymakers split on the timing of the first rate cut, with several participants preferring to wait for clearer evidence that inflation is returning sustainably to target.\n\nThe document described the labor market as 'gradually cooling' and noted that recent data had been 'mixed.' Markets trimmed bets on a near-term cut, though the broader easing path for the year was left intact.",
    source: "The Wall Street Journal",
    time: "6h ago",
    sentiment: "neutral",
    tickers: [],
  },
  {
    id: "n5",
    headline: "Broadcom custom-silicon demand accelerates on hyperscaler capex surge",
    summary: "Analysts raised price targets as cloud providers expand in-house accelerator programs, a tailwind for AVGO's ASIC business.",
    body: "Broadcom's custom-silicon business is benefiting from a surge in capital spending among the largest cloud operators, several of which are designing in-house AI accelerators to reduce reliance on merchant GPUs.\n\nAnalysts raised price targets, framing the ASIC franchise as a structural winner. The company's networking portfolio, which connects large GPU clusters, was cited as an additional beneficiary of AI data-center buildouts.",
    source: "Barron's",
    time: "8h ago",
    sentiment: "positive",
    tickers: ["AVGO"],
  },
  {
    id: "n6",
    headline: "Coinbase faces fresh SEC scrutiny over staking products",
    summary: "The regulator requested additional disclosures, reviving uncertainty around the exchange's recurring revenue streams.",
    body: "Coinbase disclosed that the Securities and Exchange Commission has requested additional information related to its staking products, reviving regulatory uncertainty around a meaningful source of recurring revenue.\n\nThe company said it believes its services comply with applicable law and intends to cooperate. The shares fell on the news as traders weighed the potential impact on the subscription-and-services segment.",
    source: "The Block",
    time: "10h ago",
    sentiment: "negative",
    tickers: ["COIN"],
  },
  {
    id: "n7",
    headline: "S&P 500 closes flat as investors weigh earnings against macro headwinds",
    summary: "Gains in megacap tech offset weakness across energy and industrials in a low-volume session.",
    body: "The S&P 500 finished little changed as strength in megacap technology offset declines across energy and industrial names. Trading volume was light ahead of key inflation data later in the week.\n\nBreadth was narrow, with a handful of large-cap names accounting for most of the index's intraday move. Volatility gauges remained subdued, suggesting limited near-term positioning shifts.",
    source: "MarketWatch",
    time: "11h ago",
    sentiment: "neutral",
    tickers: [],
  },
  {
    id: "n8",
    headline: "Apple services revenue hits record as install base tops 2.3 billion devices",
    summary: "The high-margin services segment again outgrew hardware, reinforcing the recurring-revenue thesis.",
    body: "Apple reported record services revenue, with management highlighting continued growth in subscriptions, advertising and payments across an active install base that now exceeds 2.3 billion devices.\n\nThe results eased concerns about softer iPhone upgrade cycles, as the higher-margin services mix supported overall profitability. Analysts focused on early traction for the company's on-device AI features.",
    source: "Reuters",
    time: "12h ago",
    sentiment: "positive",
    tickers: ["AAPL"],
  },
  {
    id: "n9",
    headline: "AMD slips as analysts question data-center GPU ramp timeline",
    summary: "A cautious note flagged execution risk against entrenched competition in AI accelerators.",
    body: "AMD shares declined after an analyst note questioned whether the company's next-generation data-center GPUs can ramp quickly enough to take meaningful share in a market dominated by a single incumbent.\n\nThe note acknowledged AMD's improving software stack but argued that customer qualification cycles remain long. Management has maintained that demand visibility is improving into the back half of the year.",
    source: "Seeking Alpha",
    time: "1d ago",
    sentiment: "negative",
    tickers: ["AMD"],
  },
  {
    id: "n10",
    headline: "Oil holds near three-month low as demand outlook stays cloudy",
    summary: "Crude steadied as traders balanced supply discipline against soft global demand signals.",
    body: "Crude oil steadied near a three-month low as the market weighed continued supply restraint from major producers against tepid demand indicators out of large consuming economies.\n\nEnergy equities were mixed. Traders said the path of prices will likely hinge on upcoming inventory data and any shift in guidance from producer coalitions.",
    source: "Bloomberg",
    time: "1d ago",
    sentiment: "neutral",
    tickers: ["XOM", "CVX"],
  },
];

export const MOCK_MARKET: MarketStats = {
  sentiment: 64,
  sentimentLabel: "Bullish",
  activeSignals: 1284,
  longCount: 742,
  shortCount: 401,
  advancers: 318,
  decliners: 182,
  fomcScore: -0.2,
  fomcLabel: "Dovish",
};

export const MOCK_USER: ProfileUser = {
  display_name: "Demo Trader",
  email: "you@penguinai.io",
  tier: "PRO",
  member_since: "Jan 2026",
  watchlist_count: 12,
  signals_viewed: 348,
  win_rate: 63,
};

// ── Stock universe (screener) ─────────────────────────────────────────────────
export const MOCK_UNIVERSE: UniverseRow[] = [
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

// ── Earnings calendar ─────────────────────────────────────────────────────────
// Anchored to NOW (2026-06-05). Past dates carry actuals ("reported"); future
// dates have estimates only ("upcoming"). Tickers exist in MOCK_UNIVERSE so the
// name resolves and the row links to a real /signals/[ticker] page.
const B = 1_000_000_000;

export const MOCK_EARNINGS: EarningsEvent[] = [
  // ── Reported ──
  { ticker: "PLTR", name: "Palantir Technologies", report_date: "2026-06-01", session: "AMC", eps_estimate: 0.09, eps_actual: 0.11, eps_surprise_pct: 22.2, revenue_estimate: 0.84 * B, revenue_actual: 0.87 * B, guidance_text: "Raised FY revenue guidance on accelerating US commercial bookings." },
  { ticker: "AAPL", name: "Apple Inc.", report_date: "2026-06-02", session: "BMO", eps_estimate: 1.42, eps_actual: 1.51, eps_surprise_pct: 6.3, revenue_estimate: 94.5 * B, revenue_actual: 96.2 * B, guidance_text: "Q4 revenue seen up low-double-digits on services strength." },
  { ticker: "TSLA", name: "Tesla Inc.", report_date: "2026-06-03", session: "AMC", eps_estimate: 0.71, eps_actual: 0.62, eps_surprise_pct: -12.7, revenue_estimate: 25.1 * B, revenue_actual: 24.3 * B, guidance_text: "Reiterated full-year delivery target; flagged near-term margin pressure." },
  { ticker: "AMD", name: "Advanced Micro Devices", report_date: "2026-06-03", session: "AMC", eps_estimate: 0.84, eps_actual: 0.79, eps_surprise_pct: -6.0, revenue_estimate: 6.4 * B, revenue_actual: 6.31 * B, guidance_text: null },
  { ticker: "COST", name: "Costco Wholesale", report_date: "2026-06-04", session: "AMC", eps_estimate: 4.1, eps_actual: 4.28, eps_surprise_pct: 4.4, revenue_estimate: 62.1 * B, revenue_actual: 63.0 * B, guidance_text: null },

  // ── Upcoming ──
  { ticker: "NVDA", name: "NVIDIA Corp.", report_date: "2026-06-05", session: "AMC", eps_estimate: 1.12, eps_actual: null, eps_surprise_pct: null, revenue_estimate: 41.2 * B, revenue_actual: null, guidance_text: null },
  { ticker: "AVGO", name: "Broadcom Inc.", report_date: "2026-06-06", session: "AMC", eps_estimate: 1.36, eps_actual: null, eps_surprise_pct: null, revenue_estimate: 14.9 * B, revenue_actual: null, guidance_text: null },
  { ticker: "MU", name: "Micron Technology", report_date: "2026-06-08", session: "AMC", eps_estimate: 1.21, eps_actual: null, eps_surprise_pct: null, revenue_estimate: 7.6 * B, revenue_actual: null, guidance_text: null },
  { ticker: "ORCL", name: "Oracle Corp.", report_date: "2026-06-09", session: "AMC", eps_estimate: 1.58, eps_actual: null, eps_surprise_pct: null, revenue_estimate: 15.3 * B, revenue_actual: null, guidance_text: null },
  { ticker: "COIN", name: "Coinbase Global", report_date: "2026-06-09", session: "AMC", eps_estimate: 1.04, eps_actual: null, eps_surprise_pct: null, revenue_estimate: 1.6 * B, revenue_actual: null, guidance_text: null },
  { ticker: "CRM", name: "Salesforce Inc.", report_date: "2026-06-10", session: "AMC", eps_estimate: 2.61, eps_actual: null, eps_surprise_pct: null, revenue_estimate: 9.8 * B, revenue_actual: null, guidance_text: null },
  { ticker: "LLY", name: "Eli Lilly & Co.", report_date: "2026-06-11", session: "BMO", eps_estimate: 5.42, eps_actual: null, eps_surprise_pct: null, revenue_estimate: 12.7 * B, revenue_actual: null, guidance_text: null },
  { ticker: "META", name: "Meta Platforms", report_date: "2026-06-12", session: "AMC", eps_estimate: 5.1, eps_actual: null, eps_surprise_pct: null, revenue_estimate: 42.5 * B, revenue_actual: null, guidance_text: null },
];

const r2 = (n: number) => Math.round(n * 100) / 100;
const r4 = (n: number) => Math.round(n * 10000) / 10000;

const HOLDING_BY_DIR: Record<Direction, HoldingPeriod> = {
  LONG: "SWING",
  SHORT: "SHORT_TERM",
  NEUTRAL: "INTRADAY",
};

/** A full demo Signal (ML + sentiment + AI fields) for the detail-page fallback. */
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

// ── Celebrity Holdings mock data ─────────────────────────────────────────────
export const MOCK_CELEB_HOLDINGS: CelebrityHolding[] = [
  { id: "ch1", reported_at: "2026-05-15T00:00:00Z", celebrity: "buffett", ticker: "AAPL", ticker_name: "Apple Inc.", action: "HOLD", shares: 400_000_000, value_usd: 85_720_000_000, source_type: "13F", filing_url: null },
  { id: "ch2", reported_at: "2026-05-15T00:00:00Z", celebrity: "buffett", ticker: "BAC", ticker_name: "Bank of America", action: "BUY", shares: 1_032_852_006, value_usd: 44_012_000_000, source_type: "13F", filing_url: null },
  { id: "ch3", reported_at: "2026-05-15T00:00:00Z", celebrity: "buffett", ticker: "KO", ticker_name: "Coca-Cola Co.", action: "HOLD", shares: 400_000_000, value_usd: 25_200_000_000, source_type: "13F", filing_url: null },
  { id: "ch4", reported_at: "2026-06-02T00:00:00Z", celebrity: "pelosi", ticker: "NVDA", ticker_name: "NVIDIA Corp.", action: "BUY", shares: null, value_usd: 5_000_000, source_type: "daily_disclosure", filing_url: null },
  { id: "ch5", reported_at: "2026-06-01T00:00:00Z", celebrity: "pelosi", ticker: "GOOGL", ticker_name: "Alphabet Inc.", action: "BUY", shares: null, value_usd: 1_000_000, source_type: "daily_disclosure", filing_url: null },
  { id: "ch6", reported_at: "2026-06-04T00:00:00Z", celebrity: "cathie_wood", ticker: "TSLA", ticker_name: "Tesla Inc.", action: "BUY", shares: 150_000, value_usd: null, source_type: "daily_disclosure", filing_url: null },
  { id: "ch7", reported_at: "2026-06-04T00:00:00Z", celebrity: "cathie_wood", ticker: "PLTR", ticker_name: "Palantir Technologies", action: "BUY", shares: 500_000, value_usd: null, source_type: "daily_disclosure", filing_url: null },
  { id: "ch8", reported_at: "2026-06-03T00:00:00Z", celebrity: "cathie_wood", ticker: "COIN", ticker_name: "Coinbase Global", action: "SELL", shares: 200_000, value_usd: null, source_type: "daily_disclosure", filing_url: null },
  { id: "ch9", reported_at: "2026-06-03T00:00:00Z", celebrity: "cathie_wood", ticker: "ROKU", ticker_name: "Roku Inc.", action: "BUY", shares: 350_000, value_usd: null, source_type: "daily_disclosure", filing_url: null },
  { id: "ch10", reported_at: "2026-05-15T00:00:00Z", celebrity: "soros", ticker: "AMZN", ticker_name: "Amazon.com Inc.", action: "BUY", shares: 2_000_000, value_usd: 372_600_000, source_type: "13F", filing_url: null },
  { id: "ch11", reported_at: "2026-05-15T00:00:00Z", celebrity: "soros", ticker: "MSFT", ticker_name: "Microsoft Corp.", action: "SELL", shares: 500_000, value_usd: 226_050_000, source_type: "13F", filing_url: null },
  { id: "ch12", reported_at: "2026-05-15T00:00:00Z", celebrity: "dalio", ticker: "SPY", ticker_name: "SPDR S&P 500 ETF", action: "SELL", shares: 1_500_000, value_usd: 795_000_000, source_type: "13F", filing_url: null },
  { id: "ch13", reported_at: "2026-05-20T00:00:00Z", celebrity: "tuberville", ticker: "AAPL", ticker_name: "Apple Inc.", action: "BUY", shares: null, value_usd: 250_000, source_type: "daily_disclosure", filing_url: null },
  { id: "ch14", reported_at: "2026-05-15T00:00:00Z", celebrity: "ackman", ticker: "QQQ", ticker_name: "Invesco QQQ Trust", action: "BUY", shares: 800_000, value_usd: 395_200_000, source_type: "13F", filing_url: null },
];

export const MOCK_CELEB_STATS: CelebritySummary[] = [
  { celebrity: "cathie_wood", total_trades: 156, buys: 92, sells: 64, latest_trade: "2026-06-04T00:00:00Z" },
  { celebrity: "pelosi", total_trades: 18, buys: 14, sells: 4, latest_trade: "2026-06-02T00:00:00Z" },
  { celebrity: "buffett", total_trades: 24, buys: 8, sells: 4, latest_trade: "2026-05-15T00:00:00Z" },
  { celebrity: "soros", total_trades: 31, buys: 16, sells: 15, latest_trade: "2026-05-15T00:00:00Z" },
  { celebrity: "dalio", total_trades: 42, buys: 20, sells: 22, latest_trade: "2026-05-15T00:00:00Z" },
  { celebrity: "ackman", total_trades: 12, buys: 7, sells: 5, latest_trade: "2026-05-15T00:00:00Z" },
  { celebrity: "tuberville", total_trades: 8, buys: 6, sells: 2, latest_trade: "2026-05-20T00:00:00Z" },
];
