"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import { useQuery } from "@tanstack/react-query";
import { Newspaper, ArrowRight, ExternalLink, Search, X, SlidersHorizontal } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { news as newsApi } from "@/lib/api";
import { cn, timeAgoUnix } from "@/lib/utils";
import type { NewsArticle, NewsApiArticle } from "@/lib/types";

const SENT: Record<NewsArticle["sentiment"], { label: string; chip: string }> = {
  positive: { label: "Bullish", chip: "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30" },
  negative: { label: "Bearish", chip: "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/30" },
  neutral: { label: "Neutral", chip: "text-zinc-600 dark:text-zinc-400 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600/50" },
};

const FILTERS = ["all", "positive", "negative", "neutral"] as const;

// The featured hero renders at ~800x192 — the ONLY image on the news page, so we always
// want one there. Two thresholds:
//   IDEAL  — preferred hero image; crisp at that size.
//   FLOOR  — minimum we'll still show rather than go imageless; below this an image is a
//            thumbnail/tracking pixel and looks broken stretched, so it's never used.
// Hero selection prefers an IDEAL image (+ a summary), but falls back to the largest
// FLOOR-passing image so the hero always shows a picture when the feed has any usable one.
const MIN_IMG_W = 400;
const MIN_IMG_H = 200;
const FLOOR_IMG_W = 200;
const FLOOR_IMG_H = 120;

const MAJOR_TICKERS = new Set([
  "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
  "SPY", "QQQ", "DIA", "IWM", "BRK.B", "JPM", "V", "UNH", "MA", "AVGO",
]);

function mapApiArticle(raw: NewsApiArticle): NewsArticle {
  const sent = raw.sentiment ?? "neutral";
  return {
    id: raw.id,
    headline: raw.headline,
    summary: raw.summary,
    source: raw.source,
    url: raw.url,
    image: raw.image,
    datetime: raw.datetime,
    time: timeAgoUnix(raw.datetime),
    sentiment: sent === "positive" || sent === "negative" ? sent : "neutral",
    tickers: raw.tickers,
    category: raw.category,
  };
}

const NON_EN_RE = /\b(según|también|después|años|será|está|están|puede|desde|gobierno|mercado|dijo|empresa|precio|acciones|inversión|más|país|economía|millones|sobre|entre|hasta|tienen|otros|durante|porque|contra|ainda|sobre|muito|agora|empresa|preço|ações|também)\b/i;

function isLikelyEnglish(text: string): boolean {
  if (NON_EN_RE.test(text)) return false;
  const ascii = text.replace(/[^\x20-\x7E]/g, "").length;
  return ascii / text.length > 0.85;
}

// How much a story variant carries — Massive (summary + image + real sentiment) outranks a
// Google/Finnhub headline-only dup, so dedup keeps the richer copy.
function richness(a: NewsArticle): number {
  return (a.summary ? 2 : 0) + (a.image ? 2 : 0) + (a.sentiment !== "neutral" ? 1 : 0);
}

function deduplicateArticles(articles: NewsArticle[]): NewsArticle[] {
  const norm = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();
  const seen = new Map<string, NewsArticle>();
  for (const a of articles) {
    if (!isLikelyEnglish(a.headline + " " + (a.summary ?? ""))) continue;
    // Key on the normalized headline so the same story from Massive + Google collapses
    // (their URLs differ — canonical vs Google redirect — so url-only dedup would miss it).
    const key = norm(a.headline) || a.url || "";
    if (!key) continue;
    const existing = seen.get(key);
    if (!existing) {
      seen.set(key, { ...a, tickers: [...(a.tickers ?? [])] });
    } else {
      const mergedTickers = [...new Set([...(existing.tickers ?? []), ...(a.tickers ?? [])])];
      const base = richness(a) > richness(existing) ? { ...a } : existing;
      base.tickers = mergedTickers;
      seen.set(key, base);
    }
  }
  return [...seen.values()];
}

function scoreFeatured(a: NewsArticle, hasGoodImage: boolean): number {
  let score = 0;
  const tickers = a.tickers ?? [];
  if (tickers.length === 0 || tickers.some((t) => ["SPY", "QQQ", "DIA"].includes(t))) score += 10;
  if (tickers.some((t) => MAJOR_TICKERS.has(t))) score += 5;
  if (tickers.length >= 2) score += 3;
  // Only a high-res image counts — a low-res one is no better than no image here.
  if (hasGoodImage) score += 2;
  if (a.summary && a.summary.length > 80) score += 1;
  return score;
}

export default function NewsPage() {
  const [f, setF] = useState<(typeof FILTERS)[number]>("all");
  const [searchTicker, setSearchTicker] = useState("");
  const [activeTicker, setActiveTicker] = useState<string | null>(null);

  const { data: hotArticles, isLoading: hotLoading } = useQuery<NewsArticle[]>({
    queryKey: ["hotNews"],
    queryFn: async () => {
      try {
        // fresh=true overlays a live Google News RSS pull so opening the page triggers a
        // fetch of the latest headlines, not just whatever the last ingest cycle stored.
        const raw = await newsApi.hot(100, undefined, true);
        if (raw.length > 0) return raw.map(mapApiArticle);
      } catch { /* fall through */ }
      const raw = await newsApi.market();
      return raw.map(mapApiArticle);
    },
    staleTime: 60 * 1000,
    refetchOnMount: "always",
  });

  const { data: tickerArticles, isLoading: tickerLoading } = useQuery<NewsArticle[]>({
    queryKey: ["tickerNews", activeTicker],
    queryFn: async () => {
      if (!activeTicker) return [];
      // fresh=true overlays a live Google News RSS pull for the ticker the user is
      // actively viewing — near-real-time, matching the chat agent's freshness.
      const raw = await newsApi.byTicker(activeTicker, 7, true);
      return raw.map(mapApiArticle);
    },
    enabled: !!activeTicker,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: true,
  });

  const isLoading = activeTicker ? tickerLoading : hotLoading;

  const allNews = useMemo(() => {
    const raw = (activeTicker ? tickerArticles : hotArticles) ?? [];
    return deduplicateArticles(raw);
  }, [activeTicker, tickerArticles, hotArticles]);

  const counts = useMemo(
    () => ({
      positive: allNews.filter((n) => n.sentiment === "positive").length,
      negative: allNews.filter((n) => n.sentiment === "negative").length,
      neutral: allNews.filter((n) => n.sentiment === "neutral").length,
    }),
    [allNews],
  );
  const total = allNews.length;
  const net = counts.positive >= counts.negative ? "Bullish" : "Bearish";

  // Probe candidate images for their real natural size. Broken images never load, so they
  // simply never enter the map; loaded ones record {w,h} and we rank by it. Runs only for
  // the market feed (featured is hidden in single-ticker view).
  const [imageDims, setImageDims] = useState<Map<string, { w: number; h: number }>>(new Map());
  useEffect(() => {
    if (activeTicker) return;
    const candidates = allNews.filter((a) => a.image);
    if (candidates.length === 0) {
      setImageDims(new Map());
      return;
    }
    let cancelled = false;
    const dims = new Map<string, { w: number; h: number }>();
    let pending = candidates.length;
    const settle = () => {
      pending -= 1;
      if (pending === 0 && !cancelled) setImageDims(new Map(dims));
    };
    for (const a of candidates) {
      const img = new window.Image();
      img.onload = () => {
        dims.set(a.id, { w: img.naturalWidth, h: img.naturalHeight });
        settle();
      };
      img.onerror = settle; // broken image → never recorded → never used
      img.src = a.image!;
    }
    return () => {
      cancelled = true;
    };
  }, [allNews, activeTicker]);

  const featured = useMemo(() => {
    if (activeTicker || allNews.length < 4) return [];
    const isIdeal = (a: NewsArticle) => {
      const d = imageDims.get(a.id);
      return !!d && d.w >= MIN_IMG_W && d.h >= MIN_IMG_H;
    };
    const isUsable = (a: NewsArticle) => {
      const d = imageDims.get(a.id);
      return !!d && d.w >= FLOOR_IMG_W && d.h >= FLOOR_IMG_H;
    };
    const area = (a: NewsArticle) => {
      const d = imageDims.get(a.id);
      return d ? d.w * d.h : 0;
    };

    const sorted = [...allNews].sort(
      (a, b) => scoreFeatured(b, isIdeal(b)) - scoreFeatured(a, isIdeal(a)),
    );
    // Hero (featured[0]) is the only slot that renders an image, so guarantee it has one:
    // ideal+summary → ideal → largest usable image → (only if none load) text-only.
    const hero =
      sorted.find((a) => isIdeal(a) && (a.summary?.length ?? 0) > 40) ??
      sorted.find((a) => isIdeal(a)) ??
      [...sorted].filter(isUsable).sort((a, b) => area(b) - area(a))[0] ??
      sorted[0];
    const ordered = [hero, ...sorted.filter((a) => a.id !== hero.id)].slice(0, 3);
    // Keep the image only when it actually loaded at a usable size; strip broken/tiny ones
    // so a card never shows a stretched pixel (hero already preferred a usable image above).
    return ordered.map((a) => (isUsable(a) ? a : { ...a, image: undefined }));
  }, [allNews, activeTicker, imageDims]);

  const featuredIds = useMemo(() => new Set(featured.map((a) => a.id)), [featured]);

  const feed = useMemo(() => {
    let items = allNews.filter((n) => !featuredIds.has(n.id));
    if (f !== "all") items = items.filter((n) => n.sentiment === f);
    return items;
  }, [allNews, featuredIds, f]);

  const isExternal = (n: NewsArticle) => Boolean(n.url);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const t = searchTicker.trim().toUpperCase();
    if (t) {
      setActiveTicker(t);
      setF("all");
    }
  };

  const clearSearch = () => {
    setActiveTicker(null);
    setSearchTicker("");
    setF("all");
  };

  const handleTickerClick = (ticker: string) => {
    setActiveTicker(ticker.toUpperCase());
    setSearchTicker(ticker.toUpperCase());
    setF("all");
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
          <Newspaper size={20} className="text-sky-500 dark:text-sky-400" />
          {activeTicker ? `${activeTicker} News` : "Market News"}
        </h1>
        <p className="text-sm text-zinc-500 mt-0.5">
          {activeTicker
            ? `Latest headlines for ${activeTicker}`
            : "FinBERT-scored headlines for major stocks & ETFs"}
        </p>
      </div>

      {/* Sentiment overview */}
      <Card className="p-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
            {activeTicker ? `${activeTicker} sentiment` : "Today's news sentiment"}
          </p>
          {total > 0 && (
            <span className={cn("text-sm font-semibold", net === "Bullish" ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
              {net} bias
            </span>
          )}
        </div>
        <div className="h-2 rounded-full overflow-hidden flex bg-zinc-200 dark:bg-zinc-800">
          <div className="bg-emerald-500" style={{ width: `${total > 0 ? (counts.positive / total) * 100 : 0}%` }} />
          <div className="bg-zinc-400 dark:bg-zinc-600" style={{ width: `${total > 0 ? (counts.neutral / total) * 100 : 0}%` }} />
          <div className="bg-red-500" style={{ width: `${total > 0 ? (counts.negative / total) * 100 : 0}%` }} />
        </div>
        <div className="flex gap-4 mt-2 text-xs text-zinc-500">
          <span><span className="text-emerald-600 dark:text-emerald-400 font-mono">{counts.positive}</span> bullish</span>
          <span><span className="text-zinc-700 dark:text-zinc-300 font-mono">{counts.neutral}</span> neutral</span>
          <span><span className="text-red-600 dark:text-red-400 font-mono">{counts.negative}</span> bearish</span>
        </div>
      </Card>

      {/* Loading state */}
      {isLoading && (
        <div className="text-center py-4">
          <p className="text-sm text-zinc-400 dark:text-zinc-600 animate-pulse">Loading news...</p>
        </div>
      )}

      {/* Featured — 1 large + 2 small grid. Stays pinned in the market view regardless
          of the sentiment filter (featured is already [] when a ticker search is active). */}
      {!isLoading && featured.length === 3 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* Primary featured — spans full width on mobile, left column on desktop */}
          <FeaturedCard article={featured[0]} variant="large" onTickerClick={handleTickerClick} />
          {/* Two secondary featured stacked on the right */}
          <div className="flex flex-col gap-3">
            <FeaturedCard article={featured[1]} variant="small" onTickerClick={handleTickerClick} />
            <FeaturedCard article={featured[2]} variant="small" onTickerClick={handleTickerClick} />
          </div>
        </div>
      )}

      {/* Search + Filters bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <form onSubmit={handleSearch} className="flex items-center gap-2 flex-1 min-w-[200px]">
          <div className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 focus-within:border-sky-500/60 transition-colors w-full">
            <Search size={15} className="text-zinc-500 shrink-0" />
            <input
              value={searchTicker}
              onChange={(e) => setSearchTicker(e.target.value)}
              placeholder="Search ticker (e.g. AAPL, NVDA)..."
              className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-full"
              autoComplete="off"
            />
            {activeTicker && (
              <button type="button" onClick={clearSearch} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 shrink-0">
                <X size={14} />
              </button>
            )}
          </div>
        </form>
        <div className="flex items-center gap-1">
          <SlidersHorizontal size={13} className="text-zinc-400 mr-1" />
          {FILTERS.map((x) => (
            <button
              key={x}
              onClick={() => setF(x)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                f === x
                  ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                  : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300",
              )}
            >
              {x === "all" ? "All" : SENT[x].label}
            </button>
          ))}
        </div>
      </div>

      {/* Feed */}
      <div className="space-y-3">
        {feed.map((n) => {
          const s = SENT[n.sentiment];
          const ext = isExternal(n);

          return (
            <a
              key={n.id}
              href={n.url ?? "#"}
              {...(ext ? { target: "_blank" as const, rel: "noopener noreferrer" } : {})}
              className="block group"
            >
              <Card className="p-4 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1.5 min-w-0">
                    <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100 leading-snug group-hover:text-zinc-900 dark:group-hover:text-white transition-colors">{n.headline}</h2>
                    {n.summary && (
                      <p className="text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed line-clamp-2">{n.summary}</p>
                    )}
                    <div className="flex items-center gap-2 text-xs text-zinc-400 dark:text-zinc-600 pt-1 flex-wrap">
                      <span className="text-zinc-600 dark:text-zinc-400">{n.source}</span>
                      <span>·</span>
                      <span>{n.time}</span>
                      {n.tickers && n.tickers.length > 0 && (
                        <>
                          <span>·</span>
                          <span className="flex gap-1.5 flex-wrap">
                            {n.tickers.map((t) => (
                              <button
                                key={t}
                                type="button"
                                onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleTickerClick(t); }}
                                className="font-mono text-sky-600 dark:text-sky-400 hover:underline"
                              >
                                {t}
                              </button>
                            ))}
                          </span>
                        </>
                      )}
                      {ext && <ExternalLink size={11} className="text-zinc-400 dark:text-zinc-600 ml-1" />}
                    </div>
                  </div>
                  <span className={cn("shrink-0 px-2 py-0.5 rounded-full text-[11px] font-semibold border", s.chip)}>{s.label}</span>
                </div>
              </Card>
            </a>
          );
        })}
        {!isLoading && feed.length === 0 && (
          <p className="text-center text-sm text-zinc-400 dark:text-zinc-600 py-8">
            {activeTicker
              ? `No ${f === "all" ? "" : f + " "}news found for ${activeTicker}.`
              : `No ${f} headlines right now.`}
          </p>
        )}
      </div>
    </div>
  );
}

function FeaturedCard({
  article: n,
  variant,
  onTickerClick,
}: {
  article: NewsArticle;
  variant: "large" | "small";
  onTickerClick: (t: string) => void;
}) {
  const ext = Boolean(n.url);
  const large = variant === "large";

  return (
    <a
      href={n.url ?? "#"}
      {...(ext ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      className="block group h-full"
    >
      <Card className={cn("h-full hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors", large ? "p-5" : "p-4")}>
        <div className="flex items-center gap-2 mb-2">
          <span className={cn("px-2 py-0.5 rounded-full text-[11px] font-semibold border", SENT[n.sentiment].chip)}>
            {SENT[n.sentiment].label}
          </span>
          <span className="text-xs text-zinc-400 dark:text-zinc-600">{n.source} · {n.time}</span>
          {ext && <ExternalLink size={12} className="text-zinc-400 dark:text-zinc-600" />}
        </div>
        {large && n.image && (
          <Image
            src={n.image}
            alt=""
            width={800}
            height={192}
            className="w-full h-48 object-cover rounded-md mb-3"
            unoptimized
          />
        )}
        <h2 className={cn(
          "font-bold text-zinc-900 dark:text-zinc-100 leading-snug group-hover:text-zinc-900 dark:group-hover:text-white transition-colors",
          large ? "text-lg" : "text-sm line-clamp-2",
        )}>
          {n.headline}
        </h2>
        {large && <p className="text-sm text-zinc-600 dark:text-zinc-400 mt-2 leading-relaxed line-clamp-3">{n.summary}</p>}
        {!large && n.summary && <p className="text-xs text-zinc-500 dark:text-zinc-500 mt-1 line-clamp-2">{n.summary}</p>}
        {n.tickers && n.tickers.length > 0 && (
          <div className="flex gap-1.5 mt-2 flex-wrap">
            {n.tickers.map((t) => (
              <button
                key={t}
                type="button"
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); onTickerClick(t); }}
                className="font-mono text-xs text-sky-600 dark:text-sky-400 hover:underline"
              >
                {t}
              </button>
            ))}
          </div>
        )}
        {large && (
          <span className="inline-flex items-center gap-1 text-sm text-sky-600 dark:text-sky-400 mt-3">
            {ext ? "Read on source" : "Read article"} <ArrowRight size={14} />
          </span>
        )}
      </Card>
    </a>
  );
}
