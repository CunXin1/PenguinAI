import { cn, pct, signedPct, money, compact, timeAgo, isUsMarketSessionNow } from "@/lib/utils";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("px-2", "py-1")).toBe("px-2 py-1");
  });

  it("resolves Tailwind conflicts (last wins)", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });

  it("handles conditional classes", () => {
    expect(cn("base", false && "hidden", "text-sm")).toBe("base text-sm");
  });

  it("returns empty string for no inputs", () => {
    expect(cn()).toBe("");
  });
});

describe("pct", () => {
  it("formats 0.87 as 87%", () => {
    expect(pct(0.87)).toBe("87%");
  });

  it("formats 1 as 100%", () => {
    expect(pct(1)).toBe("100%");
  });

  it("formats 0 as 0%", () => {
    expect(pct(0)).toBe("0%");
  });

  it("respects digits parameter", () => {
    expect(pct(0.8765, 2)).toBe("87.65%");
  });

  it("returns dash for null", () => {
    expect(pct(null)).toBe("—");
  });

  it("returns dash for undefined", () => {
    expect(pct(undefined)).toBe("—");
  });

  it("returns dash for NaN", () => {
    expect(pct(NaN)).toBe("—");
  });
});

describe("signedPct", () => {
  it("formats positive with + sign", () => {
    expect(signedPct(2.4)).toBe("+2.40%");
  });

  it("formats negative with - sign", () => {
    expect(signedPct(-1.5)).toBe("-1.50%");
  });

  it("formats zero with + sign", () => {
    expect(signedPct(0)).toBe("+0.00%");
  });

  it("returns dash for null", () => {
    expect(signedPct(null)).toBe("—");
  });

  it("returns dash for NaN", () => {
    expect(signedPct(NaN)).toBe("—");
  });

  it("respects digits parameter", () => {
    expect(signedPct(3.14159, 1)).toBe("+3.1%");
  });
});

describe("money", () => {
  it("formats a normal price", () => {
    expect(money(1234.5)).toBe("$1,234.50");
  });

  it("formats zero", () => {
    expect(money(0)).toBe("$0.00");
  });

  it("formats large numbers with commas", () => {
    expect(money(1000000)).toBe("$1,000,000.00");
  });

  it("returns dash for null", () => {
    expect(money(null)).toBe("—");
  });

  it("returns dash for undefined", () => {
    expect(money(undefined)).toBe("—");
  });

  it("returns dash for NaN", () => {
    expect(money(NaN)).toBe("—");
  });
});

describe("compact", () => {
  it("formats thousands as K", () => {
    expect(compact(1284)).toBe("1.3K");
  });

  it("formats millions as M", () => {
    expect(compact(2500000)).toBe("2.5M");
  });

  it("formats billions as B", () => {
    expect(compact(3200000000)).toBe("3.2B");
  });

  it("formats zero as 0", () => {
    expect(compact(0)).toBe("0");
  });

  it("returns dash for null", () => {
    expect(compact(null)).toBe("—");
  });

  it("returns dash for undefined", () => {
    expect(compact(undefined)).toBe("—");
  });
});

describe("timeAgo", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns seconds ago for < 60s", () => {
    vi.setSystemTime(new Date("2026-06-08T12:00:30Z"));
    expect(timeAgo("2026-06-08T12:00:00Z")).toBe("30s ago");
  });

  it("returns minutes ago for < 60m", () => {
    vi.setSystemTime(new Date("2026-06-08T12:05:00Z"));
    expect(timeAgo("2026-06-08T12:00:00Z")).toBe("5m ago");
  });

  it("returns hours ago for < 24h", () => {
    vi.setSystemTime(new Date("2026-06-08T15:00:00Z"));
    expect(timeAgo("2026-06-08T12:00:00Z")).toBe("3h ago");
  });

  it("returns days ago for >= 24h", () => {
    vi.setSystemTime(new Date("2026-06-10T12:00:00Z"));
    expect(timeAgo("2026-06-08T12:00:00Z")).toBe("2d ago");
  });

  it("clamps to at least 1s ago", () => {
    vi.setSystemTime(new Date("2026-06-08T12:00:00Z"));
    expect(timeAgo("2026-06-08T12:00:00Z")).toBe("1s ago");
  });
});

describe("isUsMarketActiveNow (aliased as isUsMarketSessionNow)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns true during regular session (Tue 11:00 ET)", () => {
    vi.setSystemTime(new Date("2026-06-09T15:00:00Z"));
    expect(isUsMarketSessionNow()).toBe(true);
  });

  it("returns true during pre-market (Mon 06:00 ET)", () => {
    // 06:00 ET = 10:00 UTC — within extended window [04:00, 20:00)
    vi.setSystemTime(new Date("2026-06-08T10:00:00Z"));
    expect(isUsMarketSessionNow()).toBe(true);
  });

  it("returns true during after-hours (Mon 18:00 ET)", () => {
    // 18:00 ET = 22:00 UTC — within extended window [04:00, 20:00)
    vi.setSystemTime(new Date("2026-06-08T22:00:00Z"));
    expect(isUsMarketSessionNow()).toBe(true);
  });

  it("returns false at extended close (Mon 20:00 ET)", () => {
    // 20:00 ET = 00:00 UTC next day — at the boundary, excluded
    vi.setSystemTime(new Date("2026-06-09T00:00:00Z"));
    expect(isUsMarketSessionNow()).toBe(false);
  });

  it("returns false before extended open (Mon 03:59 ET)", () => {
    // 03:59 ET = 07:59 UTC
    vi.setSystemTime(new Date("2026-06-08T07:59:00Z"));
    expect(isUsMarketSessionNow()).toBe(false);
  });

  it("returns true at extended open boundary (Mon 04:00 ET)", () => {
    // 04:00 ET = 08:00 UTC
    vi.setSystemTime(new Date("2026-06-08T08:00:00Z"));
    expect(isUsMarketSessionNow()).toBe(true);
  });

  it("returns false on Saturday", () => {
    vi.setSystemTime(new Date("2026-06-13T15:00:00Z"));
    expect(isUsMarketSessionNow()).toBe(false);
  });

  it("returns false on Sunday", () => {
    vi.setSystemTime(new Date("2026-06-14T15:00:00Z"));
    expect(isUsMarketSessionNow()).toBe(false);
  });

  it("accepts an explicit Date argument", () => {
    const wed1030ET = new Date("2026-06-10T14:30:00Z"); // Wed 10:30 ET
    expect(isUsMarketSessionNow(wed1030ET)).toBe(true);
  });
});
