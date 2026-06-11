import type {
  ActionResponse,
  AdminDataSourceStatus,
  AdminModelPerformance,
  AdminTaskStatus,
  AdminUserListResponse,
  AdminUserRow,
  AdminUserStats,
  Candle,
  CandleBar,
  CelebrityHolding,
  CelebritySummary,
  CelebrityTopHolding,
  ChartRange,
  ChatMessage,
  ChatQuota,
  ChatReply,
  DatabaseHealth,
  EarningsEvent,
  EndpointHealth,
  FearGreedCurrent,
  FearGreedHistoryPoint,
  FomcDiffResult,
  FomcMarketReaction,
  FomcNextMeeting,
  FomcRatePoint,
  FomcRateProbability,
  FomcScheduleItem,
  FomcStatement,
  FomcTrendPoint,
  HeatmapResponse,
  LogsResponse,
  MarketStatus,
  MiniQuote,
  NewsApiArticle,
  Quote,
  RegisterResponse,
  Signal,
  SignalListItem,
  SymbolRequestResult,
  SystemHealthOverview,
  TaskResultResponse,
  Ticker,
  TickerSearchResult,
  TokenResponse,
  User,
  VolatilitySeries,
  WatchlistItem,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
const DEFAULT_TIMEOUT_MS = 10_000;

// ── Auth token management ──────────────────────────────────────────────────────
function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function apiFetch<T>(path: string, options?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res: globalThis.Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json", ...authHeaders(), ...options?.headers },
      ...options,
      signal: options?.signal ?? controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timer);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw Object.assign(new Error(`Request timeout after ${timeoutMs}ms`), { status: 0, timeout: true });
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const data = await res.json().catch(() => null);
  if (res.status === 202) {
    throw Object.assign(new Error(data?.message ?? "Request accepted"), {
      status: res.status,
      data,
    });
  }

  if (!res.ok) {
    const err = data ?? { detail: res.statusText };
    throw Object.assign(new Error(err.detail ?? "API error"), { status: res.status, data: err });
  }
  return data as T;
}

// ── Auth API ───────────────────────────────────────────────────────────────────
export const auth = {
  register: (email: string, password: string, username: string, display_name?: string) =>
    apiFetch<RegisterResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, username, password, display_name }),
    }),

  login: (identifier: string, password: string) =>
    apiFetch<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ identifier, password }),
    }),

  me: () => apiFetch<User>("/auth/me"),

  forgotPassword: (email: string) =>
    apiFetch<{ message: string }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  resetPassword: (token: string, password: string) =>
    apiFetch<{ message: string }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),

  changePassword: (current_password: string, new_password: string) =>
    apiFetch<{ message: string; access_token?: string }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),

  verifyEmail: (token: string) =>
    apiFetch<{ message: string }>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  resendVerification: (email: string) =>
    apiFetch<{ message: string }>("/auth/resend-verification", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  /** Full-page redirect target to begin the OAuth flow. Navigate, don't fetch. */
  oauthStartUrl: (provider: "google" | "apple") => `${BASE_URL}/auth/oauth/${provider}`,
};

// ── Signal API ─────────────────────────────────────────────────────────────────
export const signals = {
  getTop: (limit = 100) =>
    apiFetch<SignalListItem[]>(`/signals/top?limit=${limit}`),

  getByTicker: (ticker: string, poll = false) =>
    apiFetch<Signal>(`/signals/${ticker.toUpperCase()}${poll ? "?poll=1" : ""}`),
};

// ── Symbol request API ───────────────────────────────────────────────────────
export const symbolRequests = {
  /** Log demand for a symbol we don't cover (deduped server-side by symbol). */
  create: (symbol: string) =>
    apiFetch<SymbolRequestResult>("/symbols/request", {
      method: "POST",
      body: JSON.stringify({ symbol: symbol.toUpperCase() }),
    }),
};

// ── Ticker API ─────────────────────────────────────────────────────────────────
export const tickers = {
  search: (q: string) =>
    apiFetch<TickerSearchResult[]>(`/tickers/search?q=${encodeURIComponent(q)}`),

  getUniverse: (offset = 0, limit = 100) =>
    apiFetch<Ticker[]>(`/tickers/universe?offset=${offset}&limit=${limit}`),

  get: (ticker: string) =>
    apiFetch<Ticker>(`/tickers/${ticker.toUpperCase()}`),
};

// ── Watchlist API ──────────────────────────────────────────────────────────────
export const watchlist = {
  get: () => apiFetch<WatchlistItem[]>("/watchlist"),

  add: (ticker: string) =>
    apiFetch<void>(`/watchlist/${ticker.toUpperCase()}`, { method: "POST" }),

  remove: (ticker: string) =>
    apiFetch<void>(`/watchlist/${ticker.toUpperCase()}`, { method: "DELETE" }),
};

// ── Pinned Signals API ────────────────────────────────────────────────────────
export const pinnedSignals = {
  get: () => apiFetch<string[]>("/pinned-signals"),
  set: (tickers: string[]) =>
    apiFetch<string[]>("/pinned-signals", {
      method: "PUT",
      body: JSON.stringify({ tickers }),
    }),
};

// ── Market Data API ────────────────────────────────────────────────────────────
export const marketData = {
  candles: (ticker: string, timeframe: "1min" | "30min" | "1day" = "30min", days = 30) =>
    apiFetch<{ ticker: string; timeframe: string; candles: Candle[] }>(
      `/market-data/${ticker}/candles?timeframe=${timeframe}&days=${days}`
    ),

  quotes: (tickers: string[]) =>
    apiFetch<{ quotes: Quote[] }>(
      `/market-data/quotes?tickers=${encodeURIComponent(tickers.join(","))}`
    ),

  /** Range-bucketed OHLC series (server-aggregated from 1-min bars). Powers PriceChart. */
  series: (ticker: string, range: ChartRange = "1W") =>
    apiFetch<{ ticker: string; range: ChartRange; bars: CandleBar[]; prev_close: number | null }>(
      `/market-data/${ticker.toUpperCase()}/series?range=${range}`
    ),

  /** Batch index-strip data: price + same-session %chg + intraday spark per ticker. */
  mini: (tickers: string[]) =>
    apiFetch<{ items: MiniQuote[] }>(
      `/market-data/mini?tickers=${encodeURIComponent(tickers.join(","))}`
    ),

  /** Market-cap heatmap tiles (Top-N by market cap, colored by % change over `period`). */
  heatmap: (limit = 100, period: string = "1D") =>
    apiFetch<HeatmapResponse>(`/market-data/heatmap?limit=${limit}&period=${period}`),

  /** Global "is the US market open right now" — one source of truth for LIVE badges + poll cadence. */
  status: () => apiFetch<MarketStatus>("/market-data/status"),
};

// ── Earnings API ─────────────────────────────────────────────────────────────
export const earnings = {
  /** Calendar window. `from`/`to` are ISO dates (YYYY-MM-DD). */
  calendar: (from: string, to: string) =>
    apiFetch<EarningsEvent[]>(`/earnings/calendar?from=${from}&to=${to}`),

  byTicker: (ticker: string) =>
    apiFetch<EarningsEvent[]>(`/earnings/${ticker.toUpperCase()}`),
};

// ── Celebrity Holdings API ───────────────────────────────────────────────────
export const celebrityHoldings = {
  list: (limit = 100, offset = 0) =>
    apiFetch<CelebrityHolding[]>(`/celebrity-holdings?limit=${limit}&offset=${offset}`),

  byCelebrity: (celebrity: string, limit = 100) =>
    apiFetch<CelebrityHolding[]>(`/celebrity-holdings/${celebrity}?limit=${limit}`),

  byTicker: (ticker: string, limit = 50) =>
    apiFetch<CelebrityHolding[]>(`/celebrity-holdings/ticker/${ticker.toUpperCase()}?limit=${limit}`),

  stats: () => apiFetch<CelebritySummary[]>("/celebrity-holdings/stats/summary"),

  topHoldings: (celebrity: string, limit = 30) =>
    apiFetch<CelebrityTopHolding[]>(
      `/celebrity-holdings/${celebrity}/top-holdings?limit=${limit}`
    ),
};

// ── News API ─────────────────────────────────────────────────────────────────
export const news = {
  /** Market-wide news feed (Massive → Google RSS → Finnhub, cached 5 min). */
  market: (limit = 30) =>
    apiFetch<NewsApiArticle[]>(`/news/market?limit=${limit}`),

  /** Hot ticker news from DB (pre-fetched Nasdaq-100 + key ETFs). */
  hot: (limit = 50, ticker?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (ticker) params.set("ticker", ticker.toUpperCase());
    return apiFetch<NewsApiArticle[]>(`/news/hot?${params}`);
  },

  /** Company news for a single ticker. */
  byTicker: (ticker: string, days = 7) =>
    apiFetch<NewsApiArticle[]>(`/news/${ticker.toUpperCase()}?days=${days}`),
};

// ── FOMC API ────────────────────────────────────────────────────────────────
export const fomc = {
  statements: (limit = 10) =>
    apiFetch<FomcStatement[]>(`/fomc/statements?limit=${limit}`),

  trend: (limit = 10) =>
    apiFetch<FomcTrendPoint[]>(`/fomc/trend?limit=${limit}`),

  nextMeeting: () =>
    apiFetch<FomcNextMeeting>("/fomc/next-meeting"),

  schedule: (past = 10, future = 10) =>
    apiFetch<FomcScheduleItem[]>(`/fomc/schedule?past=${past}&future=${future}`),

  rateHistory: (years = 5) =>
    apiFetch<FomcRatePoint[]>(`/fomc/rate-history?years=${years}`),

  marketReaction: (limit = 20) =>
    apiFetch<FomcMarketReaction[]>(`/fomc/market-reaction?limit=${limit}`),

  diff: (date: string) =>
    apiFetch<FomcDiffResult>(`/fomc/diff?date=${date}`),

  news: (limit = 10) =>
    apiFetch<NewsApiArticle[]>(`/fomc/news?limit=${limit}`),

  rateProbabilities: () =>
    apiFetch<FomcRateProbability[]>("/fomc/rate-probabilities"),
};

// ── Fear & Greed + Volatility API ─────────────────────────────────────────────
export const fearGreed = {
  /** Current index reading + 7 components + previous-period comparison. */
  current: () => apiFetch<FearGreedCurrent>("/fear-greed"),

  /** Daily score history for the line chart. */
  history: (days = 365) =>
    apiFetch<FearGreedHistoryPoint[]>(`/fear-greed/history?days=${days}`),

  /** VIX or VVIX daily OHLC series. */
  volatility: (symbol: "VIX" | "VVIX" = "VIX", days = 365) =>
    apiFetch<VolatilitySeries>(
      `/fear-greed/volatility?symbol=${symbol}&days=${days}`
    ),
};

// ── Chat assistant API ────────────────────────────────────────────────────────
export const chat = {
  /** Send the conversation; returns one assistant reply + updated quota.
   *  Longer timeout than default — local LLM generation can take several seconds. */
  send: (messages: ChatMessage[]) =>
    apiFetch<ChatReply>("/chat", {
      method: "POST",
      body: JSON.stringify({ messages }),
      timeoutMs: 60_000,
    }),

  /** Current remaining allowance (does not consume any). */
  quota: () => apiFetch<ChatQuota>("/chat/quota"),
};

// ── Admin API ───────────────────────────────────────────────────────────────
export const admin = {
  healthOverview: () =>
    apiFetch<SystemHealthOverview>("/admin/health/overview"),

  healthEndpoints: () =>
    apiFetch<EndpointHealth>("/admin/health/endpoints"),

  dbHealth: () =>
    apiFetch<DatabaseHealth>("/admin/db/health"),

  taskStatus: () =>
    apiFetch<AdminTaskStatus>("/admin/tasks/status"),

  datasourceStatus: () =>
    apiFetch<AdminDataSourceStatus>("/admin/datasources/status"),

  modelPerformance: () =>
    apiFetch<AdminModelPerformance>("/admin/models/performance"),

  userStats: () =>
    apiFetch<AdminUserStats>("/admin/users/stats"),

  userList: (page = 1, perPage = 20, search = "", tier = "") =>
    apiFetch<AdminUserListResponse>(
      `/admin/users?page=${page}&per_page=${perPage}&search=${encodeURIComponent(search)}&tier=${tier}`
    ),

  updateUser: (userId: string, data: { tier?: string; is_active?: boolean }) =>
    apiFetch<AdminUserRow>(`/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  triggerAction: (action: string) =>
    apiFetch<ActionResponse>(`/admin/actions/${action}`, { method: "POST" }),

  taskResult: (taskId: string) =>
    apiFetch<TaskResultResponse>(`/admin/actions/task/${taskId}`),

  logs: (lines = 100, level = "INFO") =>
    apiFetch<LogsResponse>(`/admin/logs?lines=${lines}&level=${level}`),
};
