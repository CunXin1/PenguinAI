# Frontend -- Next.js Web Application

## Overview

The PenguinAI frontend is a multi-page investment-signal dashboard built with **Next.js 15 (App Router)**, **React 19**, **TypeScript**, and **Tailwind CSS**. It communicates with the FastAPI backend and **falls back to demo data** (`src/lib/mock.ts`) when the backend is unavailable, so every page renders fully even before the data pipeline is online.

**Design rules:**

- **Dark by default, with a light theme toggle** (`components/ui/ThemeToggle.tsx`). Dark background is `#09090b` (zinc-950). Always pair colors with `dark:` variants (e.g. `bg-white dark:bg-zinc-950`) so both themes render correctly.
- LONG = emerald (`emerald-400/500`), SHORT = red (`red-400/500`), NEUTRAL = zinc (`zinc-400/500`).
- Brand accent = sky (`sky-400/500`). Numbers use the mono font.
- All API calls go through `src/lib/api.ts` -- never `fetch()` directly in components.
- Types live in `src/lib/types.ts` and must stay in sync with `backend/app/schemas/signal.py`.

## Structure

```
frontend/
├── src/
│   ├── app/                              App Router
│   │   ├── layout.tsx                    Root layout -- dark theme + <Providers> + <Navbar>
│   │   ├── providers.tsx                 React Query QueryClientProvider + MarketStatusProvider
│   │   ├── page.tsx                      Dashboard (market overview + top signals + trending + news)
│   │   ├── globals.css                   Tailwind base + custom scrollbar
│   │   ├── heatmap/page.tsx              Market-cap heatmap (treemap by market cap, colored by % change)
│   │   ├── screener/page.tsx             Stock screener -- filter / sort the universe
│   │   ├── earnings/page.tsx             Earnings calendar (date window, BMO/AMC session, EPS surprise)
│   │   ├── watchlist/page.tsx            Watchlist -- add/remove, synced to backend or localStorage
│   │   ├── news/
│   │   │   ├── page.tsx                  News feed -- sentiment overview + featured + filter
│   │   │   └── [id]/page.tsx             Article detail + related signals
│   │   ├── profile/page.tsx              Profile -- identity, tier, watchlist, settings
│   │   ├── signals/[ticker]/page.tsx     Signal detail -- price chart + SignalCard
│   │   └── auth/
│   │       ├── login/page.tsx            Login / register card UI
│   │       ├── forgot-password/page.tsx  Request password-reset email
│   │       └── reset-password/page.tsx   Set new password from reset token
│   ├── components/
│   │   ├── layout/Navbar.tsx             Sticky top nav + ticker search + theme toggle + user menu
│   │   ├── ui/                           Card, Badge, ConfidenceBar, Sparkline, StatTile, ThemeToggle, MarketStatusBadge
│   │   ├── dashboard/                    MarketIndices, MarketChart, MarketPulse, TopSignals, TrendingTickers, WatchlistWidget, NewsPreview
│   │   ├── market/Heatmap.tsx            Market-cap treemap (treemap layout + colored tiles)
│   │   ├── charts/PriceChart.tsx         TradingView Lightweight Charts (v5), dynamic import
│   │   ├── signals/SignalCard.tsx         Full signal display (ML scores, sentiment, AI analysis)
│   │   ├── signals/UnknownSymbol.tsx     Not-found / delisted symbol view
│   │   └── __tests__/components.test.tsx
│   ├── hooks/
│   │   ├── useAuth.ts                    Current user + JWT auth state
│   │   ├── useTopSignals.ts              Top signals (API-first, mock fallback, real price overlay)
│   │   ├── useLiveQuotes.ts              Live quote board from /api/market-data/quotes
│   │   ├── useTrending.ts               Trending tickers (biggest movers from Nasdaq-100 subset)
│   │   ├── useWatchlist.ts              Unified watchlist (backend when signed in, localStorage when guest)
│   │   └── __tests__/hooks.test.tsx
│   └── lib/
│       ├── api.ts                        All API client functions (the only place that calls fetch)
│       ├── types.ts                      TypeScript types (mirror backend Pydantic schemas)
│       ├── utils.ts                      cn() + money/percent/time/compact formatters + isUsMarketSessionNow
│       ├── market-status.tsx             MarketStatusProvider context + useMarketStatus hook
│       ├── mock.ts                       Demo data + deterministic candle/signal generators
│       └── __tests__/
│           ├── setup.ts                  Vitest setup (jest-dom matchers + localStorage mock)
│           ├── api.test.ts
│           └── utils.test.ts
├── vitest.config.ts                      Vitest config (jsdom, @/ alias, global setup)
├── next.config.ts                        output: "standalone" (for Docker)
├── tailwind.config.ts                    Dark theme + brand colors
├── tsconfig.json                         Strict mode, bundler resolution, @/* path alias
└── Dockerfile                            Multi-stage build (deps -> build -> runner)
```

## Pages

| Route | What it shows |
|-------|---------------|
| `/` | **Dashboard** -- MarketIndices strip, MarketPulse sentiment, MarketChart, TopSignals grid (filter by direction, sparkline + confidence), TrendingTickers sidebar, NewsPreview, WatchlistWidget. |
| `/heatmap` | **Market Map** -- market-cap treemap with configurable size (30/50/100/200 stocks) and period (1D/1W/1M/3M/1Y). Index tiles (SPY/QQQ/DIA) above the map. Live/Closed badge. Auto-polls when market is open and period is 1D. |
| `/screener` | **Screener** -- sortable table of top 500 by market cap; server-side ticker/name search across the full universe; sector filter; live price overlay for top 60 names. |
| `/earnings` | **Earnings** -- calendar grouped by date, tab filter (Upcoming/Reported/All), ticker search. Stat tiles for upcoming count, beats, misses. EPS estimate vs. actual with surprise %. BMO/AMC session badges. |
| `/watchlist` | **Watchlist** -- add/remove tickers with symbol validation (only symbols in the universe can be added); live prices + signal direction badges; synced to backend when signed in, localStorage when guest. |
| `/news` | **News** -- sentiment-overview bar (bullish/neutral/bearish counts), featured headline, sentiment filter, clickable feed. Currently reads from demo data. |
| `/news/[id]` | **Article** -- full body, related-ticker signals, sentiment badge. |
| `/profile` | **Profile** -- identity card with avatar, tier badge (FREE/PRO/PREMIUM/ADMIN), member-since date, watchlist overview (top 8), plan upgrade prompt, settings (notifications + preferences -- coming soon), sign out. Auth-gated. |
| `/signals/[ticker]` | **Signal detail** -- `PriceChart` (range-bucketed OHLC from `/series`) + full `SignalCard` (ML scores, sentiment, AI analysis). Tries API first; polls on 202 (cold ticker computing); falls back to demo `SignalCard` on error. Unknown/delisted symbols show `UnknownSymbol` view. |
| `/auth/login` | **Login / Register** -- dual-mode card; password strength meter on register (8+ chars, uppercase, lowercase, number, special); "Forgot your password?" link. |
| `/auth/forgot-password` | **Forgot Password** -- request a password-reset email. |
| `/auth/reset-password` | **Reset Password** -- set a new password using a token from the reset email. |

## Key components

### Navbar (`components/layout/Navbar.tsx`)

Sticky top bar. Desktop shows icon+label nav links, inline ticker search, theme toggle, and user avatar dropdown (or Sign in button). Mobile collapses into a hamburger menu with search. The `MarketStatusBadge` (Live/Closed) is shown on desktop. Nav entries: Dashboard, Market Map, Screener, Earnings, Watchlist, News, Profile.

### SignalCard (`components/signals/SignalCard.tsx`)

Displays a full signal: direction badge (LONG/SHORT/NEUTRAL), confidence progress bar (direction-colored), ML scores (XGBoost, Random Forest, Ensemble as pills), FinBERT sentiment score + post count, AI key drivers, AI analysis, and computation timestamp.

### PriceChart (`components/charts/PriceChart.tsx`)

TradingView Lightweight Charts v5 candlestick chart. Dynamically imported inside `useEffect` to avoid SSR. Series created with `chart.addSeries(CandlestickSeries, ...)` (v5 API). Data from `/market-data/{ticker}/series`. Shows an explicit empty state when there is no data (no mock fallback for charts).

### Heatmap (`components/market/Heatmap.tsx`)

Treemap layout where tile area is proportional to market cap and color encodes % change (red through neutral gray to green). Exported `tileGradient()` utility used by both the treemap and the index tiles.

## Hooks

| Hook | Purpose |
|------|---------|
| `useAuth` | Current user + JWT auth. Reads token from localStorage, fetches `/auth/me`, auto-clears on 401. Exposes `user`, `isLoggedIn`, `isLoading`, `logout`. |
| `useTopSignals` | Fetches `/signals/top`, falls back to `MOCK_SIGNALS`, then overlays real prices from `/market-data/quotes` and real sparklines from `/market-data/{ticker}/series`. Polls every 60s when market is open. |
| `useLiveQuotes` | Batch quote fetch for a list of tickers. Returns a `ticker -> Quote` map. Polls every 60s when market is open, stops when closed. |
| `useTrending` | Fetches quotes for a hardcoded Nasdaq-100 subset (16 liquid/volatile names), sorts by session % change, returns top N movers. Falls back to mock. |
| `useWatchlist` | Unified API: calls `/watchlist` endpoints when signed in, uses localStorage otherwise. Supports `add`, `remove`, `has`. Also exposes `signalByTicker` from server-backed watchlist items. |

## API client (`lib/api.ts`)

All HTTP calls go through `apiFetch<T>()`, which provides:
- **Base URL** from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000/api`).
- **Auth headers** -- reads JWT from `localStorage` and attaches `Authorization: Bearer <token>`.
- **Timeout** -- 10-second default via `AbortController`. Configurable per-call with `timeoutMs`. On timeout, throws an error with `{ status: 0, timeout: true }`.
- **202 handling** -- throws a structured error with `{ status: 202, data }` so callers can detect accepted-but-not-ready responses and poll.
- **204 handling** -- returns `undefined` (for DELETE endpoints).
- **Error handling** -- non-ok responses throw `{ status, data }` with parsed JSON body.

### API groups

**`auth`** -- Authentication and password management.
| Method | Endpoint | Description |
|--------|----------|-------------|
| `register(email, password, display_name?)` | `POST /auth/register` | Create account, returns `TokenResponse` |
| `login(email, password)` | `POST /auth/login` | Sign in, returns `TokenResponse` |
| `me()` | `GET /auth/me` | Current user profile |
| `forgotPassword(email)` | `POST /auth/forgot-password` | Request password reset email |
| `resetPassword(token, password)` | `POST /auth/reset-password` | Set new password from reset token |
| `changePassword(current_password, new_password)` | `POST /auth/change-password` | Change password (authenticated) |

**`signals`** -- Signal retrieval.
| Method | Endpoint | Description |
|--------|----------|-------------|
| `getTop(limit)` | `GET /signals/top` | Top signals list (default 100) |
| `getByTicker(ticker, poll?)` | `GET /signals/{ticker}` | Full signal detail; `poll=1` avoids re-triggering computation |

**`symbolRequests`** -- Data demand queue.
| Method | Endpoint | Description |
|--------|----------|-------------|
| `create(symbol)` | `POST /symbols/request` | Log demand for an uncovered symbol |

**`tickers`** -- Ticker universe.
| Method | Endpoint | Description |
|--------|----------|-------------|
| `search(q)` | `GET /tickers/search` | Server-side search by ticker or name |
| `getUniverse(offset, limit)` | `GET /tickers/universe` | Paginated universe by market cap |
| `get(ticker)` | `GET /tickers/{ticker}` | Single ticker metadata |

**`watchlist`** -- User watchlist (authenticated).
| Method | Endpoint | Description |
|--------|----------|-------------|
| `get()` | `GET /watchlist` | All watchlist items with attached signals |
| `add(ticker)` | `POST /watchlist/{ticker}` | Add ticker |
| `remove(ticker)` | `DELETE /watchlist/{ticker}` | Remove ticker |

**`marketData`** -- Market data and quotes.
| Method | Endpoint | Description |
|--------|----------|-------------|
| `candles(ticker, timeframe, days)` | `GET /market-data/{ticker}/candles` | Historical OHLCV candles |
| `quotes(tickers)` | `GET /market-data/quotes` | Batch latest prices + session % change |
| `series(ticker, range)` | `GET /market-data/{ticker}/series` | Range-bucketed OHLC bars for PriceChart |
| `mini(tickers)` | `GET /market-data/mini` | Index strip data (price + spark) |
| `heatmap(limit, period)` | `GET /market-data/heatmap` | Market-cap heatmap tiles |
| `status()` | `GET /market-data/status` | Global market open/closed status |

**`earnings`** -- Earnings calendar.
| Method | Endpoint | Description |
|--------|----------|-------------|
| `calendar(from, to)` | `GET /earnings/calendar` | Date-windowed earnings events |
| `byTicker(ticker)` | `GET /earnings/{ticker}` | Earnings history for one ticker |

## Market status

The app has a global market open/closed state managed by `MarketStatusProvider` (in `lib/market-status.tsx`), mounted at the app root.

- **Primary source:** polls `GET /market-data/status` every 15 seconds. The backend decides based on the exchange calendar (handles NYSE holidays and early closes) and live tick activity.
- **Fallback:** `isUsMarketSessionNow()` in `lib/utils.ts` -- a client-side approximation that checks ET weekday 09:30-16:00. This is used when the backend is unreachable. It does **not** account for holidays or early closes.
- **Consumer:** `useMarketStatus()` hook. Returns `{ isOpen, status, isLoading }`. Used by the Navbar badge, heatmap page, and all polling hooks (`useTopSignals`, `useLiveQuotes`, `useTrending`) to gate live-polling (poll every 60s when open, stop when closed).

## Demo-data fallback

There is no backend dependency to view the UI. Hooks try the live API first and silently fall back to demo data:

```typescript
// hooks/useTopSignals.ts
try {
  const list = await signals.getTop(60);
  base = list?.length ? list.map(toView) : MOCK_SIGNALS;
} catch {
  base = MOCK_SIGNALS;
}
```

Mock generators in `lib/mock.ts` (e.g. `mockSignalDetail`) are **deterministic** (seeded by ticker, fixed time anchor) so server and client render identically -- no hydration mismatch. Sections with no live endpoint yet (news, trending, market stats) read mock directly. The price chart has **no** mock fallback -- `PriceChart` renders only real `/market-data/{ticker}/series` bars, with an empty state when there is no data.

## Testing

The frontend uses **Vitest** + **Testing Library** (React) + **jsdom** + **MSW** (Mock Service Worker).

### Running tests

```bash
make test-frontend          # from repo root
cd frontend && npx vitest run   # direct
cd frontend && npx vitest       # watch mode
```

### Test structure

Tests live in `__tests__/` directories next to the source they test:

| File | Tests | What it covers |
|------|-------|----------------|
| `lib/__tests__/api.test.ts` | 11 | `apiFetch` timeout, 202/204/error handling, auth header injection, all API group methods |
| `lib/__tests__/utils.test.ts` | 41 | `cn`, `pct`, `signedPct`, `money`, `compact`, `isUsMarketSessionNow`, `timeAgo` |
| `hooks/__tests__/hooks.test.tsx` | 10 | `useAuth`, `useLiveQuotes`, `useTrending`, `useWatchlist` with mocked API |
| `components/__tests__/components.test.tsx` | 10 | `SignalCard`, `Navbar`, `Badge`, `Card`, `ConfidenceBar` rendering |

**72 tests total, all passing.**

Setup file (`lib/__tests__/setup.ts`) registers `@testing-library/jest-dom` matchers and provides a `localStorage` mock for the jsdom environment.

## Dependencies

### Runtime
| Package | Purpose |
|---------|---------|
| `next` 15.5 | Framework (App Router, standalone output) |
| `react` / `react-dom` 19 | UI |
| `@tanstack/react-query` 5 | Data fetching, caching, polling |
| `lightweight-charts` 5 | TradingView candlestick charts |
| `zustand` 5 | Lightweight state management |
| `lucide-react` | Icons |
| `clsx` + `tailwind-merge` | Conditional class names |

### Dev
| Package | Purpose |
|---------|---------|
| `typescript` 5 | Type checking |
| `tailwindcss` 3 | Styling |
| `vitest` 3 | Test runner |
| `@testing-library/react` + `jest-dom` + `user-event` | Component testing |
| `msw` 2 | API mocking in tests |
| `jsdom` | Browser environment for tests |
| `eslint` + `eslint-config-next` | Linting |

## Setup and running

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000 (hot reload with Turbopack)
npm run build        # production build (output: standalone)
npm run type-check   # tsc --noEmit
npm run lint         # next lint
npm run test         # vitest run
```

Environment variable: `NEXT_PUBLIC_API_URL` -- backend API base (default `http://localhost:8000/api`).

## Adding a page / component

1. Page -> `src/app/<path>/page.tsx`; add `"use client"` only if it needs state/browser APIs.
2. Add a nav entry in `components/layout/Navbar.tsx` (`NAV` array) if it is top-level.
3. Component -> `src/components/<category>/<Name>.tsx`, **named export**.
4. Reuse `ui/` primitives; derive all colors from `direction` -- never hardcode signal colors.
5. Use `cn()` (clsx + tailwind-merge) for conditional classes.
6. Add tests in a `__tests__/` directory alongside the source file.
