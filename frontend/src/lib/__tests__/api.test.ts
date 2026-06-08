import { auth, signals, marketData } from "@/lib/api";

const BASE_URL = "http://localhost:8000/api";

function mockFetchResponse(status: number, body: unknown = null, ok = status >= 200 && status < 300) {
  const res = {
    status,
    ok,
    json: vi.fn().mockResolvedValue(body),
    headers: new Headers(),
  } as unknown as Response;
  return vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>().mockResolvedValue(res);
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiFetch: auth headers", () => {
  it("includes Authorization header when access_token is present", async () => {
    localStorage.setItem("access_token", "test-token-123");
    const fetchMock = mockFetchResponse(200, { access_token: "t", token_type: "bearer" });
    vi.stubGlobal("fetch", fetchMock);

    await auth.me();

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toEqual(
      expect.objectContaining({ Authorization: "Bearer test-token-123" })
    );
  });

  it("omits Authorization header when no token", async () => {
    const fetchMock = mockFetchResponse(200, { access_token: "t", token_type: "bearer" });
    vi.stubGlobal("fetch", fetchMock);

    await auth.me();

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).not.toHaveProperty("Authorization");
  });
});

describe("apiFetch: status handling", () => {
  it("returns parsed JSON on 200", async () => {
    const payload = { id: "1", email: "a@b.com", tier: "FREE" };
    vi.stubGlobal("fetch", mockFetchResponse(200, payload));

    const result = await auth.me();
    expect(result).toEqual(payload);
  });

  it("returns undefined on 204", async () => {
    const res = {
      status: 204,
      ok: true,
      json: vi.fn().mockRejectedValue(new Error("no body")),
      headers: new Headers(),
    } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));

    const result = await auth.me();
    expect(result).toBeUndefined();
  });

  it("throws with status 202 (accepted / polling)", async () => {
    const body = { message: "Computing signal", task_id: "abc" };
    const res = {
      status: 202,
      ok: true,
      json: vi.fn().mockResolvedValue(body),
      headers: new Headers(),
    } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));

    await expect(signals.getByTicker("AAPL")).rejects.toMatchObject({
      status: 202,
      message: "Computing signal",
      data: body,
    });
  });

  it("throws with status 404", async () => {
    const body = { detail: "Not found" };
    vi.stubGlobal("fetch", mockFetchResponse(404, body, false));

    await expect(signals.getByTicker("ZZZZ")).rejects.toMatchObject({
      status: 404,
      message: "Not found",
    });
  });

  it("throws with status 500", async () => {
    const body = { detail: "Internal Server Error" };
    vi.stubGlobal("fetch", mockFetchResponse(500, body, false));

    await expect(auth.me()).rejects.toMatchObject({
      status: 500,
      message: "Internal Server Error",
    });
  });
});

describe("auth.login", () => {
  it("sends POST to /auth/login with email and password", async () => {
    const tokenResp = { access_token: "tok", token_type: "bearer" };
    const fetchMock = mockFetchResponse(200, tokenResp);
    vi.stubGlobal("fetch", fetchMock);

    const result = await auth.login("user@example.com", "secret");

    expect(result).toEqual(tokenResp);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE_URL}/auth/login`);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      email: "user@example.com",
      password: "secret",
    });
  });
});

describe("signals.getTop", () => {
  it("fetches /signals/top with default limit", async () => {
    const fetchMock = mockFetchResponse(200, []);
    vi.stubGlobal("fetch", fetchMock);

    await signals.getTop();

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE_URL}/signals/top?limit=100`);
  });

  it("fetches /signals/top with custom limit", async () => {
    const fetchMock = mockFetchResponse(200, []);
    vi.stubGlobal("fetch", fetchMock);

    await signals.getTop(10);

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE_URL}/signals/top?limit=10`);
  });
});

describe("marketData.quotes", () => {
  it("encodes tickers in URL", async () => {
    const fetchMock = mockFetchResponse(200, { quotes: [] });
    vi.stubGlobal("fetch", fetchMock);

    await marketData.quotes(["AAPL", "MSFT", "GOOG"]);

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE_URL}/market-data/quotes?tickers=${encodeURIComponent("AAPL,MSFT,GOOG")}`);
  });
});
