import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Signal } from "@/lib/types";

// ── Mocks ────────────────────────────────────────────────────────────────────

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, back: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock useAuth for Navbar
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: undefined,
    isLoggedIn: false,
    isLoading: false,
    logout: vi.fn(),
  }),
  userInitial: () => "U",
}));

// Mock market-status for MarketStatusBadge (used inside Navbar)
vi.mock("@/lib/market-status", () => ({
  useMarketStatus: () => ({ isOpen: false, isLoading: false, status: undefined }),
  MarketStatusProvider: ({ children }: { children: ReactNode }) => children,
}));

// Mock ThemeToggle — it accesses document.documentElement and is not under test
vi.mock("@/components/ui/ThemeToggle", () => ({
  ThemeToggle: () => <button aria-label="Toggle theme">theme</button>,
}));

// Mock MarketStatusBadge — it depends on context; the Navbar integration test
// only cares about the search-to-route flow, not the badge itself.
vi.mock("@/components/ui/MarketStatusBadge", () => ({
  MarketStatusBadge: ({ className }: { className?: string }) => (
    <span className={className}>CLOSED</span>
  ),
}));

// ── Shared test data ─────────────────────────────────────────────────────────

const baseMockSignal: Signal = {
  ticker: "AAPL",
  direction: "LONG",
  confidence: 0.85,
  holding_period: "SHORT_TERM",
  ml_scores: { xgb_prob_up: 0.8, rf_prob_up: 0.7, ensemble_prob: 0.75 },
  sentiment: { finbert_score: 0.6, post_count: 42, hawk_dove_ref: null },
  ai_attribution: "Strong momentum",
  ai_analysis: "Trending up",
  tier_required: "FREE",
  computed_at: new Date().toISOString(),
  expires_at: new Date().toISOString(),
};

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
});

// ── SignalCard ────────────────────────────────────────────────────────────────

describe("SignalCard", () => {
  const load = () =>
    import("@/components/signals/SignalCard").then((m) => m.SignalCard);

  it("renders LONG direction with emerald styling", async () => {
    const SignalCard = await load();
    const { container } = render(
      <SignalCard signal={{ ...baseMockSignal, direction: "LONG" }} />
    );

    const badge = screen.getByText("LONG");
    expect(badge).toBeInTheDocument();
    // The badge should carry the emerald style class
    expect(badge.className).toMatch(/emerald/);
    // Confidence bar color
    const bar = container.querySelector("[style]");
    expect(bar?.className).toMatch(/emerald/);
  });

  it("renders SHORT direction with red styling", async () => {
    const SignalCard = await load();
    const { container } = render(
      <SignalCard signal={{ ...baseMockSignal, direction: "SHORT", confidence: 0.72 }} />
    );

    const badge = screen.getByText("SHORT");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toMatch(/red/);
    const bar = container.querySelector("[style]");
    expect(bar?.className).toMatch(/red/);
  });

  it("renders NEUTRAL direction appropriately", async () => {
    const SignalCard = await load();
    render(
      <SignalCard signal={{ ...baseMockSignal, direction: "NEUTRAL" }} />
    );

    const badge = screen.getByText("NEUTRAL");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toMatch(/zinc/);
  });

  it("does not crash when ml_scores and sentiment are null-ish", async () => {
    const SignalCard = await load();
    const nullSignal: Signal = {
      ...baseMockSignal,
      ml_scores: { xgb_prob_up: null, rf_prob_up: null, ensemble_prob: null },
      sentiment: { finbert_score: null, post_count: null, hawk_dove_ref: null },
      ai_attribution: null,
      ai_analysis: null,
    };

    // Should render without throwing
    const { container } = render(<SignalCard signal={nullSignal} />);
    expect(container).toBeTruthy();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    // ML scores section should not render (all values null → ScorePill returns null)
    expect(screen.queryByText("XGBoost")).not.toBeInTheDocument();
  });
});

// ── ConfidenceBar ────────────────────────────────────────────────────────────

describe("ConfidenceBar", () => {
  const load = () =>
    import("@/components/ui/ConfidenceBar").then((m) => m.ConfidenceBar);

  it("sets width style to 75% for value=0.75", async () => {
    const ConfidenceBar = await load();
    const { container } = render(<ConfidenceBar value={0.75} />);

    const inner = container.querySelector("[style]") as HTMLElement;
    expect(inner).toBeTruthy();
    expect(inner.style.width).toBe("75%");
  });

  it("clamps values above 1.0 to 100%", async () => {
    const ConfidenceBar = await load();
    const { container } = render(<ConfidenceBar value={1.5} />);

    const inner = container.querySelector("[style]") as HTMLElement;
    expect(inner.style.width).toBe("100%");
  });

  it("clamps negative values to 0%", async () => {
    const ConfidenceBar = await load();
    const { container } = render(<ConfidenceBar value={-0.2} />);

    const inner = container.querySelector("[style]") as HTMLElement;
    expect(inner.style.width).toBe("0%");
  });
});

// ── Sparkline ────────────────────────────────────────────────────────────────

describe("Sparkline", () => {
  const load = () =>
    import("@/components/ui/Sparkline").then((m) => m.Sparkline);

  it("renders an SVG when given valid data", async () => {
    const Sparkline = await load();
    const { container } = render(
      <Sparkline data={[10, 20, 15, 25, 30]} />
    );

    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    const polyline = svg?.querySelector("polyline");
    expect(polyline).toBeInTheDocument();
  });

  it("renders nothing for an empty array", async () => {
    const Sparkline = await load();
    const { container } = render(<Sparkline data={[]} />);

    const svg = container.querySelector("svg");
    expect(svg).toBeNull();
  });
});

// ── Navbar ───────────────────────────────────────────────────────────────────

describe("Navbar", () => {
  const load = () =>
    import("@/components/layout/Navbar").then((m) => m.Navbar);

  it("navigates to /signals/AAPL when searching for 'aapl'", async () => {
    const user = userEvent.setup();
    const Navbar = await load();
    const Wrapper = createWrapper();

    render(
      <Wrapper>
        <Navbar />
      </Wrapper>
    );

    // The Navbar has two search inputs (desktop + mobile). Use the first visible one.
    const inputs = screen.getAllByPlaceholderText("Search ticker...");
    const searchInput = inputs[0];

    await user.type(searchInput, "aapl");
    await user.keyboard("{Enter}");

    expect(mockPush).toHaveBeenCalledWith("/signals/AAPL");
  });
});
