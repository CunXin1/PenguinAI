# Frontend Pages Reference

> Last updated: 2026-06-10. Next.js 15 App Router, all pages client-rendered (`"use client"`).

## Page Index

| Route | Page | Data Source | Auth | Status |
|-------|------|-------------|------|--------|
| `/` | Dashboard | Real API + mock fallback | — | Complete |
| `/signals/[ticker]` | Signal Detail | Real API (202 polling) | — | Complete |
| `/screener` | Stock Screener | Real API | — | Complete |
| `/earnings` | Earnings Calendar | Real API (no mock fallback) | — | Complete |
| `/heatmap` | Market Heatmap | Real API | — | Complete |
| `/watchlist` | Watchlist | API (logged in) / localStorage (guest) | Optional | Complete |
| `/celebrity-holdings` | Smart Money | Real API + mock fallback | — | Complete |
| `/celebrity-holdings/[slug]` | Celebrity Detail | Real API | — | Complete |
| `/news` | News Feed | Real API | — | Complete |
| `/fear-greed` | Fear & Greed Index | Real API | — | Complete |
| `/fomc` | FOMC Tracker | Real API | — | Complete |
| `/profile` | User Profile | Real API | Required | Complete |
| `/auth/login` | Login / Register | Real API | — | Complete |
| `/auth/callback` | OAuth Callback | Real API (token fragment) | — | Complete |
| `/auth/verify-email` | Verify Email | Real API (token param) | — | Complete |
| `/auth/verify-pending` | Verify Pending | Real API | Optional | Complete |
| `/auth/forgot-password` | Forgot Password | Real API | — | Complete |
| `/auth/reset-password` | Reset Password | Real API (token param) | — | Complete |
| `/admin` | Admin Dashboard | Real API (12 endpoints) | ADMIN | Complete |

---

## Page Details

### Dashboard (`/`)

Market overview with 7 widget components in a responsive grid layout.

**Widgets:**
- **MarketIndices** — SPY/QQQ/DIA/IWM strip via `/market-data/mini`
- **MarketPulse** — Sentiment summary, FOMC score, advancers/decliners
- **MarketChart** — Intraday/multi-timeframe candlestick chart
- **TopSignals** — Top signals enriched with live prices + sparklines (`useTopSignals`)
- **TrendingTickers** — Top movers by change_pct from Nasdaq-100 subset (`useTrending`)
- **NewsPreview** — Recent articles via `news.market()`
- **WatchlistWidget** — User's tracked tickers with live quotes

**API endpoints:** `/market-data/mini`, `/market-data/quotes`, `/market-data/heatmap`, `/signals/top`, `/market-data/{ticker}/series`

---

### Signal Detail (`/signals/[ticker]`)

Full signal analysis for a single ticker with price chart and AI-generated analysis.

**View states:**
1. `loading` — Skeleton while fetching
2. `computing` — 202 response received; polls `?poll=1` up to 10 times (50s max)
3. `live` — Cache hit, full signal displayed
4. `demo` — API failed or timeout, falls back to mock signal
5. `unknown` — 404 with `reason: "not_in_universe"` or `"delisted"`

**Components:** `PriceChart` (TradingView Lightweight Charts), `SignalCard` (direction/confidence/ML scores/sentiment/AI analysis), `UnknownSymbol` (404 view with coverage request button)

**API endpoints:** `/signals/{ticker}`, `/market-data/{ticker}/series`

---

### Stock Screener (`/screener`)

Searchable, sortable table of the full stock universe with live quotes overlay.

**Features:**
- Search by ticker prefix or company name (calls `/tickers/search?q=`)
- Default view: top 500 by market cap from `/tickers/universe`
- Sector filter derived from universe data
- Sortable columns: ticker, market_cap, change_pct (toggle asc/desc)
- Live quotes overlay for top 60 tickers via `useLiveQuotes`
- Each row links to `/signals/{ticker}`

**API endpoints:** `/tickers/universe`, `/tickers/search`, `/market-data/quotes`

---

### Earnings Calendar (`/earnings`)

Earnings events grouped by date with EPS tracking, expandable per-ticker history, and real-time data from the Finnhub earnings pipeline.

**View states:**
1. `loading` — Skeleton placeholder (4 stat tiles + 3 date groups)
2. `error` — Error banner with retry button (backend offline or table empty)
3. `empty` — "No earnings data yet" with `make fetch-earnings` guidance
4. `data` — Full calendar view

**Features:**
- Stat tiles (4): Upcoming / Beats / Misses / Avg Surprise %
- Tabs: Upcoming / Reported / All
- Search by ticker or company name
- Session badges: BMO (pre-market, amber), AMC (after-hours, indigo), TBD (zinc)
- EPS surprise % with color coding (emerald = beat, red = miss)
- Date grouping with "Today" badge
- Expandable rows: click any row to show per-ticker historical earnings (lazy-loaded via `GET /earnings/{ticker}`)
- EPS sparkline: inline SVG trend chart in expanded detail (last 8 reported quarters)
- Revenue display: shows actual revenue when reported, estimate otherwise
- Guidance text: displayed when available in expanded detail
- Signal link: each expanded section links to `/signals/{ticker}`

**API endpoints:** `/earnings/calendar?from={date}&to={date}`, `/earnings/{ticker}`

**Note:** No mock fallback — uses real API data only. Backend auto-fetches Finnhub earnings on startup + 2×/day. See `docs/earnings.md` for full module docs.

---

### Market Heatmap (`/heatmap`)

Market-cap weighted treemap with color-coded tiles by period performance.

**Features:**
- Period selector: 1D / 1W / 1M / 3M / 1Y
- Size selector: 30 / 50 / 100 / 200 stocks
- Index tiles: SPY, QQQ, DIA, IWM
- Breadth stats: stocks up / down / avg change
- Live/Closed market status badge
- Auto-refresh: polls every 15s for 1D when market is open; static for historical periods
- Color gradient: deep red (-3%) → neutral → deep green (+3%), scaled by period

**API endpoints:** `/market-data/heatmap?limit={n}&period={period}`

---

### Fear & Greed (`/fear-greed`)

CNN-style market-sentiment dashboard: composite Fear & Greed gauge plus the VIX/VVIX volatility charts.

**Features:**
- Hero gauge: 0–100 gradient bar + previous close / 1W / 1M / 1Y comparison strip
- Fear & Greed Over Time chart — range selector: 1M / 5M / 1Y / 5Y (real CNN data back to ~2020-09)
- 7-component breakdown (momentum, strength, breadth, put/call, volatility, junk-bond, safe-haven)
- VIX / VVIX volatility chart — range selector: 1M / 3M / 6M / 1Y / 5Y (VIX history back to 1990)
- Source badge: "CNN Business", or "estimated from VIX" when CNN is unavailable

**API endpoints:** `/fear-greed`, `/fear-greed/history?days={n}`, `/fear-greed/volatility?symbol={VIX|VVIX}&days={n}`

---

### Watchlist (`/watchlist`)

Personal list of tracked tickers with live prices and signal badges.

**Dual storage mode:**
- **Guest:** localStorage key `penguinai_watchlist`, defaults to `["NVDA","TSLA","AAPL","PLTR"]`
- **Logged in:** syncs to backend via `/watchlist` API (GET/POST/DELETE)

**Features:**
- Add ticker form with universe validation
- Live quotes via `useLiveQuotes`
- Signal direction badges (LONG/SHORT/NEUTRAL) when available
- Remove button per ticker
- Empty state with link to screener

**API endpoints:** `/watchlist`, `/market-data/quotes`, `/tickers/{ticker}` (validation)

---

### Smart Money (`/celebrity-holdings`)

Celebrity and institutional investor stock transactions.

**Features:**
- Stat tiles: Celebrities tracked / Recent buys / Recent sells
- Celebrity cards (horizontal scroll, max 8): avatar initials, name, title, buy/sell counts, latest activity — click to filter
- Filter bar: Action filter (All/Buy/Sell/Hold), active celebrity chip, ticker/name search
- Transaction table: Ticker+Name, Celebrity, Action badge (emerald/red/zinc), Shares, Value, Date, Source type
- Each row links to `/signals/{ticker}`

**Tracked:** Buffett, Soros, Dalio, Ackman (13F), Cathie Wood (ARK), Pelosi, Tuberville, MTG, Crenshaw (Congress), Trump (13D/DJT)

**API endpoints:** `/celebrity-holdings`, `/celebrity-holdings/stats/summary`

**Note:** Falls back to `MOCK_CELEB_HOLDINGS` / `MOCK_CELEB_STATS` if API unavailable. Backend auto-fetches data on startup and daily at 19:00 ET.

---

### News Feed (`/news`)

Filterable news feed with FinBERT sentiment analysis.

**Features:**
- Featured article card
- Sentiment overview (bullish/bearish/neutral bar)
- Sentiment filter tabs
- Ticker mention tags linking to signal pages
- Source attribution and timestamps
- Ticker filter: hot news (default) vs. market vs. per-ticker feed

**API endpoints:** `news.hot()`, `news.market()`, `news.byTicker(ticker)` — backed by the `news_articles` hypertable (Massive → Google News RSS → Finnhub, FinBERT-scored).

---

### User Profile (`/profile`)

Account information, plan details, and watchlist preview.

**Features:**
- Avatar with user initial, display name, email, tier badge
- Tier styling: FREE=zinc, PRO=sky, PREMIUM=purple, ADMIN=amber
- Plan card with current tier and upgrade prompt
- Watchlist preview (first 8 items)
- Settings section (Notifications, Preferences — both "coming soon")
- Sign out button

**Auth gate:** Shows a "Sign in to view profile" prompt if not authenticated.

**API endpoints:** `/auth/me`, `/watchlist`

---

### Login / Register (`/auth/login`)

Dual-mode authentication form.

**Login mode:** Email + password → POST `/auth/login` → store token → redirect home
**Register mode:** Email + password + confirm + display name → POST `/auth/register` → store token → redirect home

**Password strength meter** (register only): 8+ chars, uppercase, lowercase, digit, special character. All 5 required.

**API endpoints:** `/auth/login`, `/auth/register`

---

### Forgot Password (`/auth/forgot-password`)

Email-only form for requesting a password reset.

Always shows "Check your email" success regardless of whether the email exists (prevents enumeration). Links back to login.

**API endpoints:** `/auth/forgot-password`

---

### Reset Password (`/auth/reset-password?token=xxx`)

New password form with strength validation, accessed via email link.

**States:**
- Form: enter new password + confirm
- Success: "Password has been reset" with 3s auto-redirect to login
- Error: invalid/expired token message

**API endpoints:** `/auth/reset-password`

---

### Admin Dashboard (`/admin`)

Full-featured system administration dashboard. ADMIN tier only — non-admins see an "Access Denied" card. ADMIN users are auto-redirected here after login.

**9 monitoring panels** in responsive grid layout (`max-w-7xl`, wider than standard pages):

| Panel | Component | Polling | API Endpoint |
|-------|-----------|---------|-------------|
| System Health | `HealthOverview` | 30s | `/admin/health/overview` |
| Database | `DatabaseHealth` | 60s | `/admin/db/health` |
| API Endpoints | `EndpointHealth` | 60s | `/admin/health/endpoints` |
| Tasks & Workers | `TaskStatus` | 15s | `/admin/tasks/status` |
| Data Sources | `DataSourceStatus` | 30s | `/admin/datasources/status` |
| Models | `ModelPerformance` | 5min | `/admin/models/performance` |
| Users | `UserManagement` | 60s | `/admin/users/stats` + `/admin/users` |
| Manual Actions | `ManualActions` | manual | `/admin/actions/{action}` |
| System Logs | `SystemLogs` | manual/10s | `/admin/logs` |

**Theme:** Full light/dark mode support — all components use `dark:` Tailwind variants.

**Error handling:** Every panel has 3 states: loading skeleton, error (with Retry button), success.

**Navbar integration:** "Admin" link in user dropdown menu + mobile menu, only visible when `user.tier === "ADMIN"`.

**Admin account:** Auto-seeded on backend startup via `check_and_seed_admin()`. Configure in `.env` (`ADMIN_EMAIL` / `ADMIN_PASSWORD`).

**Shared components:** Reuses `Card`, `StatTile` from `components/ui/`. New reusable `StatusDot` (green/yellow/red/gray indicator).

> 详细文档见 [admin-dashboard.md](./admin-dashboard.md)

---

## Error Boundaries

| File | Scope | Behavior |
|------|-------|----------|
| `loading.tsx` | Per-route | Spinner + "Loading..." during route transitions |
| `not-found.tsx` | Global 404 | "404 / Page not found" with Go Home + Search Stocks links |
| `error.tsx` | Per-route errors | Error message (dev only), digest (prod), Try Again + Go Home |
| `global-error.tsx` | Root crash | Self-contained `<html>` with digest, Try Again + Go Home |

---

## Shared Infrastructure

### Navbar Search Autocomplete

- Debounced 250ms API call to `/tickers/search?q=`
- Dropdown: up to 8 results showing ticker (bold), name, sector
- Keyboard navigation: ↑↓ to highlight, Enter to select, Escape to close
- Click-outside closes dropdown
- Fallback: Enter with no highlight navigates to `/signals/{TYPED_TICKER}`

### Hooks

| Hook | Purpose | Data Source | Polling |
|------|---------|-------------|---------|
| `useAuth` | User + login state | `/auth/me` | On mount + route change |
| `useWatchlist` | Ticker list + signals | API or localStorage | — |
| `useTopSignals` | Top signals + prices + sparklines | `/signals/top` + quotes + series | 60s (market open only) |
| `useTrending` | Top movers by change_pct | `/market-data/quotes` | 60s (market open only) |
| `useLiveQuotes` | Ticker → Quote map | `/market-data/quotes` | 60s (market open only) |
| `useMarketStatus` | Market open/closed | `/market-data/status` | 15s always |

### Market-Aware Polling

`useTopSignals`, `useTrending`, and `useLiveQuotes` all read `useMarketStatus()` to gate `refetchInterval`:
- Market open → poll every 60s
- Market closed → no polling (`refetchInterval: false`)

This prevents unnecessary API load outside trading hours.

### Data Fallback Strategy

All signal/market hooks follow the same pattern:
1. Attempt real API call
2. On success → use live data
3. On failure → fall back to `MOCK_*` constants from `src/lib/mock.ts`
4. UI never goes blank — always shows something

---

## What's Not Built

| Feature | What Exists | What's Missing |
|---------|-------------|----------------|
| Profile settings | "Coming soon" UI | Notifications/preferences implementation |
| Payment/upgrade | Upgrade button in profile | Stripe integration, tier change flow |
