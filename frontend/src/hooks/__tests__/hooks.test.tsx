import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ────────────────────────────────────────────────────────────────────

// next/navigation — used by useAuth (usePathname, useRouter)
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, back: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

// @/lib/api — individual named exports that the hooks import
const mockAuthMe = vi.fn();
const mockWatchlistGet = vi.fn();
const mockWatchlistAdd = vi.fn();
const mockWatchlistRemove = vi.fn();
const mockMarketDataQuotes = vi.fn();
const mockSignalsGetTop = vi.fn();
const mockMarketDataSeries = vi.fn();
const mockMarketDataStatus = vi.fn();

vi.mock("@/lib/api", () => ({
  auth: { me: (...a: unknown[]) => mockAuthMe(...a) },
  watchlist: {
    get: (...a: unknown[]) => mockWatchlistGet(...a),
    add: (...a: unknown[]) => mockWatchlistAdd(...a),
    remove: (...a: unknown[]) => mockWatchlistRemove(...a),
  },
  marketData: {
    quotes: (...a: unknown[]) => mockMarketDataQuotes(...a),
    series: (...a: unknown[]) => mockMarketDataSeries(...a),
    status: (...a: unknown[]) => mockMarketDataStatus(...a),
  },
  signals: {
    getTop: (...a: unknown[]) => mockSignalsGetTop(...a),
  },
}));

// @/lib/market-status — useLiveQuotes imports useMarketStatus
vi.mock("@/lib/market-status", () => ({
  useMarketStatus: () => ({ isOpen: false, isLoading: false, status: undefined }),
  MarketStatusProvider: ({ children }: { children: ReactNode }) => children,
}));

// ── Helpers ──────────────────────────────────────────────────────────────────

function createWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryWrapper";
  return Wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

// ── useAuth ──────────────────────────────────────────────────────────────────

describe("useAuth", () => {
  // Lazy-import so module-level mocks are in place first.
  const load = () => import("@/hooks/useAuth").then((m) => m.useAuth);

  it("returns isLoggedIn=false when no token is present", async () => {
    const useAuth = await load();
    const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });
    expect(result.current.isLoggedIn).toBe(false);
    expect(result.current.user).toBeUndefined();
    // auth.me should NOT have been called
    expect(mockAuthMe).not.toHaveBeenCalled();
  });

  it("triggers /auth/me when a token is in localStorage", async () => {
    localStorage.setItem("access_token", "valid-jwt");
    mockAuthMe.mockResolvedValue({
      id: "u1",
      email: "test@example.com",
      display_name: "Test",
      tier: "FREE",
      created_at: "2026-01-01T00:00:00Z",
    });

    const useAuth = await load();
    const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isLoggedIn).toBe(true);
      expect(result.current.user?.email).toBe("test@example.com");
    });
    expect(mockAuthMe).toHaveBeenCalled();
  });

  it("clears the token when auth.me rejects (401)", async () => {
    localStorage.setItem("access_token", "expired-jwt");
    mockAuthMe.mockRejectedValue(
      Object.assign(new Error("Unauthorized"), { status: 401 })
    );

    const useAuth = await load();
    const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isLoggedIn).toBe(false));
    expect(localStorage.getItem("access_token")).toBeNull();
  });
});

// ── useWatchlist ─────────────────────────────────────────────────────────────

describe("useWatchlist", () => {
  const load = () => import("@/hooks/useWatchlist").then((m) => m.useWatchlist);

  it("returns default tickers from localStorage when not logged in", async () => {
    // No token → useAuth().isLoggedIn = false → guest mode
    const useWatchlist = await load();
    const { result } = renderHook(() => useWatchlist(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.tickers).toEqual(["NVDA", "TSLA", "AAPL", "PLTR"]);
  });

  it("add/remove updates the local watchlist (guest mode)", async () => {
    const useWatchlist = await load();
    const { result } = renderHook(() => useWatchlist(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.ready).toBe(true));

    await act(async () => {
      await result.current.add("MSFT");
    });
    expect(result.current.tickers).toContain("MSFT");

    await act(async () => {
      await result.current.remove("MSFT");
    });
    expect(result.current.tickers).not.toContain("MSFT");
  });

  it("has() correctly checks ticker membership", async () => {
    const useWatchlist = await load();
    const { result } = renderHook(() => useWatchlist(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.has("NVDA")).toBe(true);
    expect(result.current.has("nvda")).toBe(true); // case-insensitive
    expect(result.current.has("XYZ")).toBe(false);
  });
});

// ── useLiveQuotes ────────────────────────────────────────────────────────────

describe("useLiveQuotes", () => {
  const load = () => import("@/hooks/useLiveQuotes").then((m) => m.useLiveQuotes);

  it("returns empty object when the API fails", async () => {
    mockMarketDataQuotes.mockRejectedValue(new Error("Network error"));

    const useLiveQuotes = await load();
    const { result } = renderHook(() => useLiveQuotes(["AAPL"]), {
      wrapper: createWrapper(),
    });

    // initialData is {}, and the queryFn catches errors and returns {}
    await waitFor(() => expect(result.current.data).toEqual({}));
  });
});

// ── useTopSignals ────────────────────────────────────────────────────────────

describe("useTopSignals", () => {
  const load = () => import("@/hooks/useTopSignals").then((m) => m.useTopSignals);

  it("falls back to MOCK_SIGNALS when the API fails", async () => {
    mockSignalsGetTop.mockRejectedValue(new Error("Backend down"));
    // withRealMarketData also calls marketData.quotes — let it fail gracefully
    mockMarketDataQuotes.mockRejectedValue(new Error("no quotes"));
    mockMarketDataSeries.mockRejectedValue(new Error("no series"));

    const useTopSignals = await load();
    const { result } = renderHook(() => useTopSignals(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.data!.length).toBeGreaterThan(0);
    });
    // The first mock signal should be NVDA (from MOCK_SIGNALS)
    expect(result.current.data![0].ticker).toBe("NVDA");
  });
});

// ── useTrending ──────────────────────────────────────────────────────────────

describe("useTrending", () => {
  const load = () => import("@/hooks/useTrending").then((m) => m.useTrending);

  it("sorts results by change_pct descending", async () => {
    mockMarketDataQuotes.mockResolvedValue({
      quotes: [
        { ticker: "NVDA", price: 100, change_pct: 1.0 },
        { ticker: "TSLA", price: 200, change_pct: 5.0 },
        { ticker: "AMD", price: 150, change_pct: 3.0 },
      ],
    });

    const useTrending = await load();
    const { result } = renderHook(() => useTrending(3), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      // Wait until data reflects the API response (sorted by change_pct desc)
      expect(result.current.data![0].ticker).toBe("TSLA");
    });
    expect(result.current.data![1].ticker).toBe("AMD");
    expect(result.current.data![2].ticker).toBe("NVDA");
  });

  it("falls back to MOCK_TRENDING on API failure", async () => {
    mockMarketDataQuotes.mockRejectedValue(new Error("Network error"));

    const useTrending = await load();
    const { result } = renderHook(() => useTrending(3), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.data!.length).toBeGreaterThan(0);
    });
    // MOCK_TRENDING first entry is SMCI
    expect(result.current.data![0].ticker).toBe("SMCI");
  });
});
