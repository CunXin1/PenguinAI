import type {
  Candle,
  CandleBar,
  ChartRange,
  EarningsEvent,
  HeatmapResponse,
  MarketStatus,
  MiniQuote,
  Quote,
  Signal,
  SignalListItem,
  SymbolRequestResult,
  Ticker,
  TickerSearchResult,
  TokenResponse,
  User,
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
  register: (email: string, password: string, display_name?: string) =>
    apiFetch<TokenResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name }),
    }),

  login: (email: string, password: string) =>
    apiFetch<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
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
    apiFetch<{ message: string }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
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
    apiFetch<{ ticker: string; range: ChartRange; bars: CandleBar[] }>(
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
