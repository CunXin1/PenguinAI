import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { SessionPhase } from "@/lib/types";

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

/** Parse ET time parts from a Date (shared by the helpers below). */
function etTimeParts(now: Date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const wd = get("weekday");
  let hh = parseInt(get("hour"), 10);
  if (hh === 24) hh = 0;
  return { wd, mins: hh * 60 + parseInt(get("minute"), 10) };
}

/** Client-side session phase approximation (ET-based, no holiday awareness).
 *  Lightweight fallback when /market-data/status is unreachable. */
export function getClientSessionPhase(now: Date = new Date()): SessionPhase {
  const { wd, mins } = etTimeParts(now);
  if (wd === "Sat" || wd === "Sun") return "CLOSED";
  if (mins < 4 * 60) return "OVERNIGHT";
  if (mins < 9 * 60 + 30) return "PRE_MARKET";
  if (mins < 16 * 60) return "REGULAR";
  if (mins < 20 * 60) return "AFTER_HOURS";
  return "OVERNIGHT";
}

/** Client-side US market-active approximation (ET weekday 04:00–20:00,
 *  covering pre-market, regular, and after-hours).
 *  Lightweight fallback when /market-data/status is unreachable — does NOT
 *  account for holidays or early closes; the backend (exchange_calendars) is
 *  authoritative. */
const _ACTIVE_PHASES: ReadonlySet<SessionPhase> = new Set(["PRE_MARKET", "REGULAR", "AFTER_HOURS"]);

export function isUsMarketActiveNow(now: Date = new Date()): boolean {
  return _ACTIVE_PHASES.has(getClientSessionPhase(now));
}

/** @deprecated Use isUsMarketActiveNow — kept for backward compat. */
export const isUsMarketSessionNow = isUsMarketActiveNow;

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
