import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind class names with conflict resolution. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** 0.0–1.0 → "87%" */
export function pct(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

/** A raw percent value (2.4 → "+2.40%") with sign. */
export function signedPct(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

/** USD currency. */
export function money(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** 1284 → "1.3K" */
export function compact(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

/** Client-side US regular-session approximation (ET weekday 09:30–16:00).
 *  Lightweight fallback when /market-data/status is unreachable — does NOT
 *  account for holidays or early closes; the backend (exchange_calendars) is
 *  authoritative. On a holiday this returns true but the data feed won't
 *  advance, so ticks_advancing keeps the badge correct once the backend recovers. */
export function isUsMarketSessionNow(now: Date = new Date()): boolean {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const wd = get("weekday");
  if (wd === "Sat" || wd === "Sun") return false;
  let hh = parseInt(get("hour"), 10);
  if (hh === 24) hh = 0;
  const mins = hh * 60 + parseInt(get("minute"), 10);
  return mins >= 9 * 60 + 30 && mins < 16 * 60;
}

/** ISO timestamp → relative "3h ago" (client-side use). */
export function timeAgo(iso: string): string {
  const diff = Math.max(1, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (diff < 60) return `${diff}s ago`;
  const m = Math.floor(diff / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/** Unix timestamp (seconds) → relative "3h ago" (client-side use). */
export function timeAgoUnix(epoch: number): string {
  const diff = Math.max(1, Math.floor((Date.now() - epoch * 1000) / 1000));
  if (diff < 60) return `${diff}s ago`;
  const m = Math.floor(diff / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
