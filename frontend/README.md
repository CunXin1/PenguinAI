# Frontend — Next.js Web Application

## English

### Overview

The PenguinAI frontend is a dark-themed, multi-page investment-signal dashboard built with **Next.js 15 (App Router)**, **React 19**, **TypeScript**, and **Tailwind CSS**. It prefers the live FastAPI backend and **falls back to demo data** (`src/lib/mock.ts`) when the backend is unavailable, so every page renders fully even before the data pipeline is online.

**Design rules (non-negotiable):**
- Dark theme only — background `#09090b` (zinc-950). No white backgrounds, ever.
- LONG = emerald (`emerald-400/500`), SHORT = red (`red-400/500`), NEUTRAL = zinc (`zinc-400/500`).
- Brand accent = sky (`sky-400/500`). Numbers use the mono font.
- All API calls go through `src/lib/api.ts` — never `fetch()` directly in components.
- Types live in `src/lib/types.ts` and must stay in sync with `backend/app/schemas/signal.py`.

### Structure

```
frontend/
├── src/
│   ├── app/                          App Router
│   │   ├── layout.tsx                Root layout — dark theme + <Providers> + <Navbar>
│   │   ├── providers.tsx             React Query QueryClientProvider (client)
│   │   ├── page.tsx                  Dashboard (market pulse + top signals + trending + news)
│   │   ├── globals.css               Tailwind base + custom scrollbar
│   │   ├── screener/page.tsx         Stock screener — filter / sort the universe
│   │   ├── watchlist/page.tsx        Watchlist — add/remove, persisted to localStorage
│   │   ├── news/
│   │   │   ├── page.tsx              News feed — sentiment overview + featured + filter
│   │   │   └── [id]/page.tsx         Article detail (server component) + related signals
│   │   ├── profile/page.tsx          Profile — identity, tier, watchlist, settings
│   │   ├── signals/[ticker]/page.tsx Signal detail — candlestick chart + SignalCard
│   │   └── auth/login/page.tsx       Login / register (dark card UI)
│   ├── components/
│   │   ├── layout/Navbar.tsx         Sticky top nav + ticker search
│   │   ├── ui/                       Card, Badge, ConfidenceBar, Sparkline, StatTile
│   │   ├── dashboard/                MarketPulse, TopSignals, TrendingTickers, NewsPreview
│   │   ├── charts/CandleChart.tsx    TradingView Lightweight Charts (v5), dynamic import
│   │   └── signals/SignalCard.tsx    Full signal display card
│   ├── hooks/
│   │   └── useTopSignals.ts          React Query hook — API first, mock fallback
│   └── lib/
│       ├── api.ts                    All API client functions (the only place that fetch()es)
│       ├── types.ts                  TypeScript types (mirror backend schemas)
│       ├── utils.ts                  cn() + money/percent/time formatters
│       └── mock.ts                   Demo data + deterministic candle/signal generators
├── next.config.ts                    output: "standalone" (for Docker)
├── tailwind.config.ts                Dark theme + brand colors
└── Dockerfile                        Multi-stage build (deps → build → runner)
```

### Pages

| Route | What it shows |
|-------|---------------|
| `/` | **Dashboard** — market-pulse stat tiles, Top Signals grid (filter by direction, sparkline + confidence), Trending list, Latest-news preview. |
| `/screener` | **Screener** — sortable table of the stock universe; filter by sector and by ticker/name. |
| `/watchlist` | **Watchlist** — add/remove tickers (persisted to `localStorage`); shows direction, confidence, price, sparkline. |
| `/news` | **News** — sentiment-overview bar, featured headline, sentiment filter, clickable feed. |
| `/news/[id]` | **Article** — full body, related-ticker signals, sentiment badge. |
| `/profile` | **Profile** — identity card, tier/upgrade, watchlist, settings. |
| `/signals/[ticker]` | **Signal detail** — candlestick chart + full `SignalCard` (ML scores, sentiment, AI analysis). Tries API, polls on 202, falls back to demo. |
| `/auth/login` | Dual-mode login / register; stores JWT in `localStorage`. |

### Demo-data fallback pattern

There is no backend dependency to view the UI. Live data is fetched where an endpoint exists, with a silent fallback:

```typescript
// hooks/useTopSignals.ts
queryFn: async () => {
  try {
    const list = await signals.getTop(60);
    return list?.length ? list.map(toView) : MOCK_SIGNALS;
  } catch {
    return MOCK_SIGNALS;        // backend down → demo data, no error surfaced
  }
}
```

Mock generators in `lib/mock.ts` (e.g. `mockSignalDetail`) are **deterministic** (seeded by ticker, fixed time anchor) so server and client render identically — no hydration mismatch. Sections with no endpoint yet (news, trending, market stats) read mock directly. The price chart has **no** mock fallback — `PriceChart` renders real `/market-data/{ticker}/series` bars only, with an explicit empty state when there's no data.

### Charts

Candlesticks use **TradingView Lightweight Charts v5** (`lightweight-charts`). The library is **dynamically imported inside `useEffect`** so it never runs during SSR:

```typescript
const { createChart, ColorType, CandlestickSeries } = await import("lightweight-charts");
const chart = createChart(el, { autoSize: true, /* dark theme */ });
const series = chart.addSeries(CandlestickSeries, { upColor: "#10b981", downColor: "#ef4444" });
series.setData(bars);   // bars: { time: unixSeconds, open, high, low, close }
```

> v5 note: series are created with `chart.addSeries(CandlestickSeries, …)`, **not** v4's `addCandlestickSeries`.

### Running in this environment (Docker)

Node/npm are **not installed on the host**, and `docker.io` is blocked, so the frontend runs in a container off a locally-cached `node:22-alpine` (pulled via the DaoCloud mirror).

```powershell
# one-time: get the base image through a working mirror
docker pull docker.m.daocloud.io/library/node:22-alpine
docker tag  docker.m.daocloud.io/library/node:22-alpine node:22-alpine

# run the dev server (source bind-mounted, deps installed inside the container)
docker run -d --name penguinai-frontend -p 3000:3000 `
  -v "D:\PenguinAI\frontend:/app" -v /app/node_modules -v /app/.next -w /app `
  -e NEXT_PUBLIC_API_URL=http://localhost:8000/api `
  node:22-alpine sh -c "npm install && npm run dev -- --hostname 0.0.0.0"
```

Then open **http://localhost:3000**.

> ⚠️ **Hot reload does not work** over the Windows→Linux bind mount (inotify events aren't propagated). After editing files, **`docker restart penguinai-frontend`** to apply (re-reads everything on startup, ~20s). To get true hot reload, recreate with `-e WATCHPACK_POLLING=true` and webpack (`npx next dev`, drop `--turbo`).

### Running with native Node (if installed)

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000 (hot reload works natively)
npm run build        # production build (output: standalone)
npm run type-check   # tsc --noEmit
```

### Adding a page / component

1. Page → `src/app/<path>/page.tsx`; add `"use client"` only if it needs state/browser APIs.
2. Add a nav entry in `components/layout/Navbar.tsx` (`NAV` array) if it's top-level.
3. Component → `src/components/<category>/<Name>.tsx`, **named export**.
4. Reuse `ui/` primitives; derive all colors from `direction` — never hardcode signal colors.
5. Use `cn()` (clsx + tailwind-merge) for conditional classes.

---

## 中文

### 模块概述

PenguinAI 前端是基于 **Next.js 15（App Router）、React 19、TypeScript、Tailwind CSS** 的暗黑风多页投研信号看板。优先调用后端 API,后端不可用时**自动回退到 demo 数据**(`src/lib/mock.ts`),所以数据管线还没上线也能看到完整页面。

### 设计规范(不可违反)

- **永远暗黑主题**,背景 `#09090b`,禁止白色背景
- 做多 `emerald-400/500`、做空 `red-400/500`、中性 `zinc-400/500`;品牌色 `sky-400/500`;数字用等宽字体
- 组件内**禁止**直接 `fetch()`,统一走 `src/lib/api.ts`
- 类型在 `src/lib/types.ts`,必须与后端 Pydantic Schema 同步

### 页面

仪表盘 `/` · 选股器 `/screener` · 自选股 `/watchlist` · 新闻 `/news` 与文章详情 `/news/[id]` · 个人 `/profile` · 信号详情 `/signals/[ticker]`(含 K 线)· 登录 `/auth/login`。

### Demo 数据回退

`lib/mock.ts` 里的生成器(如 `mockSignalDetail`)是**确定性的**(用 ticker 做种子 + 固定时间锚点),保证 SSR 与客户端渲染一致、不会水合错位。没有对应后端接口的板块(新闻、热门、市场概览)直接用 mock。价格图表**不再**有 mock 兜底——`PriceChart` 只渲染真实的 `/market-data/{ticker}/series` 数据,没数据时显示空状态。

### 在本机环境运行(Docker)

本机**没装 Node**、且 `docker.io` 被墙,前端跑在容器里(`node:22-alpine` 经 DaoCloud 镜像源拉取):

```powershell
docker pull docker.m.daocloud.io/library/node:22-alpine
docker tag  docker.m.daocloud.io/library/node:22-alpine node:22-alpine
docker run -d --name penguinai-frontend -p 3000:3000 `
  -v "D:\PenguinAI\frontend:/app" -v /app/node_modules -v /app/.next -w /app `
  node:22-alpine sh -c "npm install && npm run dev -- --hostname 0.0.0.0"
```

> ⚠️ Windows bind mount **不会热重载** —— 改完代码要 `docker restart penguinai-frontend`(约 20 秒重读全部文件)才生效。

### K 线图

统一用 **TradingView Lightweight Charts v5**,在 `useEffect` 里**动态 import**(避免 SSR 报错);v5 用 `chart.addSeries(CandlestickSeries, …)` 创建序列(不是 v4 的 `addCandlestickSeries`)。
