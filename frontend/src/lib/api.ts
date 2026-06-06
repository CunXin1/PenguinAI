import type {
  Candle,
  EarningsEvent,
  Quote,
  Signal,
  SignalListItem,
  Ticker,
  TickerSearchResult,
  TokenResponse,
  User,
  WatchlistItem,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

// ── Auth token management ──────────────────────────────────────────────────────
function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders(), ...options?.headers },
    ...options,
  });
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
};

// ── Signal API ─────────────────────────────────────────────────────────────────
export const signals = {
  getTop: (limit = 100) =>
    apiFetch<SignalListItem[]>(`/signals/top?limit=${limit}`),

  getByTicker: (ticker: string) =>
    apiFetch<Signal>(`/signals/${ticker.toUpperCase()}`),
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
};

// ── Earnings API ─────────────────────────────────────────────────────────────
export const earnings = {
  /** Calendar window. `from`/`to` are ISO dates (YYYY-MM-DD). */
  calendar: (from: string, to: string) =>
    apiFetch<EarningsEvent[]>(`/earnings/calendar?from=${from}&to=${to}`),

  byTicker: (ticker: string) =>
    apiFetch<EarningsEvent[]>(`/earnings/${ticker.toUpperCase()}`),
};
