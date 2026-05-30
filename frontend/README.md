# Frontend — Next.js Web Application

## English

### Overview

The PenguinAI frontend is a dark-themed investment signal dashboard built with Next.js 15 (App Router), TypeScript, and Tailwind CSS. It fetches signals from the FastAPI backend and renders them in a professional, data-dense UI.

**Design rules (non-negotiable):**
- Dark theme only — background `#09090b` (zinc-950). No white backgrounds ever.
- LONG signals: emerald green (`emerald-400/500`)
- SHORT signals: red (`red-400/500`)
- NEUTRAL signals: zinc gray (`zinc-400/500`)
- All API calls go through `src/lib/api.ts` — never `fetch()` directly in components
- Types live in `src/lib/types.ts` — must stay in sync with `backend/app/schemas/signal.py`

### Structure

```
frontend/
├── src/
│   ├── app/                    Next.js App Router pages
│   │   ├── layout.tsx          Root layout (dark theme, fonts)
│   │   ├── page.tsx            Home — Top signals grid
│   │   ├── globals.css         Tailwind base + custom scrollbar
│   │   ├── signals/
│   │   │   └── [ticker]/
│   │   │       └── page.tsx    Signal detail page (polls on 202)
│   │   ├── watchlist/
│   │   │   └── page.tsx        User watchlist (TODO)
│   │   ├── screener/
│   │   │   └── page.tsx        Stock screener (TODO)
│   │   └── auth/
│   │       └── login/
│   │           └── page.tsx    Login + register (dark card UI)
│   ├── components/
│   │   ├── signals/
│   │   │   └── SignalCard.tsx  Core signal display card
│   │   ├── dashboard/          Market overview components (TODO)
│   │   ├── charts/             TradingView Lightweight Charts (TODO)
│   │   └── ui/                 Shared primitives (TODO)
│   ├── lib/
│   │   ├── api.ts              All API client functions
│   │   └── types.ts            TypeScript type definitions
│   └── hooks/                  Custom React hooks (TODO)
├── package.json
├── next.config.ts              standalone output for Docker
├── tailwind.config.ts          Dark theme + brand colors
├── tsconfig.json               strict mode + @/* alias
├── postcss.config.js           Tailwind + autoprefixer
└── Dockerfile                  Multi-stage build (deps → build → runner)
```

### Pages

#### Home (`/`)
Displays a real-time grid of Top-100 signals. Each cell shows:
- Ticker symbol
- Direction badge (LONG / SHORT / NEUTRAL) with color coding
- Confidence progress bar
- Click → navigates to signal detail page

#### Signal Detail (`/signals/[ticker]`)
Full signal card for a specific ticker with:
- Direction + confidence meter
- ML model probability scores (XGBoost, RF, Ensemble)
- FinBERT sentiment score + post count
- AI attribution (key drivers, ≤150 chars)
- AI analysis (professional summary, ≤300 chars)
- 202 polling: shows skeleton loader while ML worker computes

#### Login / Register (`/auth/login`)
Dual-mode auth card (toggle between Sign in / Sign up). Stores JWT in `localStorage`.

### Key Components

#### `SignalCard`
Located at `src/components/signals/SignalCard.tsx`. Accepts a `Signal` object and renders the complete signal UI. Used on both the detail page and (future) watchlist page.

Props: `{ signal: Signal }`

#### API Client (`src/lib/api.ts`)
All backend communication is centralized here. Functions return typed promises. Automatically attaches `Authorization: Bearer <token>` header from `localStorage`.

```typescript
import { signals, tickers, watchlist, auth, marketData } from "@/lib/api";

// Examples
const topSignals = await signals.getTop(100);
const signal = await signals.getByTicker("NVDA");
const results = await tickers.search("NVD");
await watchlist.add("NVDA");
```

### Installing and Running

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000 (hot reload)
npm run build        # production build
npm run type-check   # TypeScript check without building
npm run lint         # ESLint
```

### Adding a New Page

1. Create `src/app/your-path/page.tsx`
2. Mark with `"use client"` if it needs browser APIs or state
3. Use `@/lib/api` for data fetching
4. Add navigation link in the layout or nav component

### Adding a New Component

1. Create in `src/components/category/ComponentName.tsx`
2. Export named (not default) for tree-shaking
3. Keep all color logic based on `signal.direction` — never hardcode colors
4. Use `clsx` + `tailwind-merge` for conditional class names

### Charts

All candlestick charts use **TradingView Lightweight Charts** (`lightweight-charts` package).

```typescript
import { createChart } from "lightweight-charts";

const chart = createChart(containerRef.current, {
  layout: { background: { color: "#09090b" }, textColor: "#a1a1aa" },
  grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
});
```

---

## 中文

### 模块概述

PenguinAI 前端是基于 Next.js 15（App Router）、TypeScript 和 Tailwind CSS 构建的暗黑风投研信号看板。所有 API 调用通过 `src/lib/api.ts` 统一管理，类型定义在 `src/lib/types.ts` 中，必须与后端 Pydantic Schema 保持同步。

### 设计规范（不可违反）

- **永远暗黑主题**，背景色 `#09090b`，禁止白色背景
- 做多（LONG）：`emerald-400/500`（祖母绿）
- 做空（SHORT）：`red-400/500`（红色）
- 中性（NEUTRAL）：`zinc-400/500`（灰色）
- **禁止**在组件内直接调用 `fetch()`，必须通过 `src/lib/api.ts`
- 图表统一使用 **TradingView Lightweight Charts**

### 信号详情页轮询逻辑

```
GET /api/signals/{ticker}
  ├─ 200 → 直接渲染信号卡片
  └─ 202 → 显示骨架屏动画，5秒后重试，最多重试3次
```

### 本地开发

```bash
cd frontend
npm install
npm run dev   # 访问 http://localhost:3000
```

### 新增页面步骤

1. 在 `src/app/` 下创建目录和 `page.tsx`
2. 如需浏览器 API 或状态，添加 `"use client"` 指令
3. 数据获取使用 `@/lib/api`
4. 颜色逻辑基于 `signal.direction` 动态计算，禁止硬编码颜色
