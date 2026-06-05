"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Shield, Star, Bell, LogOut, Settings, Crown } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { MOCK_USER, MOCK_SIGNALS } from "@/lib/mock";
import { cn } from "@/lib/utils";
import type { UserTier } from "@/lib/types";

const TIER_STYLE: Record<UserTier, string> = {
  FREE: "text-zinc-300 bg-zinc-700/40 border-zinc-600",
  PRO: "text-sky-400 bg-sky-500/10 border-sky-500/40",
  PREMIUM: "text-amber-400 bg-amber-500/10 border-amber-500/40",
  ADMIN: "text-red-400 bg-red-500/10 border-red-500/40",
};

export default function ProfilePage() {
  const [authed, setAuthed] = useState(true);
  useEffect(() => {
    setAuthed(typeof window !== "undefined" && !!localStorage.getItem("access_token"));
  }, []);

  const u = MOCK_USER;
  const watch = MOCK_SIGNALS.slice(0, 5);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      {/* Identity */}
      <Card className="p-6">
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-gradient-to-br from-sky-400 to-sky-600 grid place-items-center text-2xl font-bold text-white">
            {u.display_name?.[0] ?? "U"}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold text-white">{u.display_name}</h1>
              <span
                className={cn(
                  "px-2 py-0.5 rounded-full text-[11px] font-semibold border flex items-center gap-1",
                  TIER_STYLE[u.tier]
                )}
              >
                <Crown size={11} /> {u.tier}
              </span>
            </div>
            <p className="text-sm text-zinc-500">{u.email}</p>
            <p className="text-xs text-zinc-600 mt-1">Member since {u.member_since}</p>
          </div>
          {!authed && (
            <Link
              href="/auth/login"
              className="px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-white text-sm font-semibold shrink-0"
            >
              Sign in
            </Link>
          )}
        </div>

        <div className="grid grid-cols-3 gap-3 mt-5">
          <Stat label="Watchlist" value={u.watchlist_count} />
          <Stat label="Signals Viewed" value={u.signals_viewed} />
          <Stat label="Win Rate" value={`${u.win_rate}%`} accent />
        </div>
      </Card>

      {/* Plan */}
      <Card className="p-5">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <Shield size={18} className="text-sky-400 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-zinc-200">Current plan: {u.tier}</p>
              <p className="text-xs text-zinc-500">
                Top-100 daily signals · upgrade for full 2,000-stock real-time coverage
              </p>
            </div>
          </div>
          <button className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-sky-500 to-sky-600 hover:from-sky-400 hover:to-sky-500 text-white text-sm font-semibold transition-colors">
            Upgrade
          </button>
        </div>
      </Card>

      {/* Watchlist */}
      <Card className="p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-zinc-200 flex items-center gap-2">
            <Star size={15} className="text-amber-400" /> My Watchlist
          </h2>
          <Link href="/" className="text-xs text-zinc-500 hover:text-sky-400 transition-colors">
            Browse signals
          </Link>
        </div>
        <div className="divide-y divide-zinc-800">
          {watch.map((s) => (
            <Link
              key={s.ticker}
              href={`/signals/${s.ticker}`}
              className="flex items-center justify-between py-2.5 -mx-2 px-2 rounded-md hover:bg-zinc-800/30 transition-colors"
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className="font-mono font-semibold text-sm text-zinc-200 w-14 shrink-0">{s.ticker}</span>
                <span className="text-xs text-zinc-500 truncate">{s.name}</span>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className="text-xs font-mono text-zinc-400">{Math.round(s.confidence * 100)}%</span>
                <DirectionBadge direction={s.direction} />
              </div>
            </Link>
          ))}
        </div>
      </Card>

      {/* Settings */}
      <Card className="p-2">
        {[
          { icon: Bell, label: "Notifications", sub: "Signal alerts & price moves", danger: false },
          { icon: Settings, label: "Preferences", sub: "Theme, default holding period", danger: false },
          { icon: LogOut, label: "Sign out", sub: "", danger: true },
        ].map((it) => (
          <button
            key={it.label}
            className="w-full flex items-center gap-3 px-3 py-3 rounded-lg hover:bg-zinc-800/50 transition-colors text-left"
          >
            <it.icon size={17} className={it.danger ? "text-red-400" : "text-zinc-400"} />
            <div className="flex-1">
              <p className={cn("text-sm font-medium", it.danger ? "text-red-400" : "text-zinc-200")}>{it.label}</p>
              {it.sub && <p className="text-xs text-zinc-500">{it.sub}</p>}
            </div>
          </button>
        ))}
      </Card>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: ReactNode; accent?: boolean }) {
  return (
    <div className="rounded-lg bg-zinc-800/40 p-3 text-center">
      <p className={cn("text-lg font-bold font-mono", accent ? "text-emerald-400" : "text-zinc-200")}>{value}</p>
      <p className="text-[11px] text-zinc-500 mt-0.5">{label}</p>
    </div>
  );
}
