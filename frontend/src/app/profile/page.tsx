"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { Shield, Star, Bell, LogOut, Settings, Crown, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { DirectionBadge } from "@/components/ui/Badge";
import { useAuth, userInitial } from "@/hooks/useAuth";
import { useWatchlist } from "@/hooks/useWatchlist";
import { cn } from "@/lib/utils";
import type { UserTier } from "@/lib/types";

const TIER_STYLE: Record<UserTier, string> = {
  FREE: "text-zinc-700 dark:text-zinc-300 bg-zinc-200 dark:bg-zinc-700/40 border-zinc-300 dark:border-zinc-600",
  PRO: "text-sky-600 dark:text-sky-400 bg-sky-500/10 border-sky-500/40",
  PREMIUM: "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/40",
  ADMIN: "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/40",
};

export default function ProfilePage() {
  const { user, isLoggedIn, isLoading, logout } = useAuth();
  const { tickers, signalByTicker } = useWatchlist();

  // Loading the session
  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-20 grid place-items-center">
        <Loader2 size={22} className="animate-spin text-sky-500" />
      </div>
    );
  }

  // Signed out → gate the page
  if (!isLoggedIn || !user) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-6">
        <Card className="p-10 text-center">
          <Shield size={28} className="text-zinc-300 dark:text-zinc-700 mx-auto mb-3" />
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Sign in to view your profile.</p>
          <Link
            href="/auth/login"
            className="inline-flex mt-4 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-white text-sm font-semibold transition-colors"
          >
            Sign in
          </Link>
        </Card>
      </div>
    );
  }

  const name = user.display_name || user.email.split("@")[0];
  const memberSince = new Date(user.created_at);
  const memberDays = Math.max(
    0,
    Math.floor((Date.now() - memberSince.getTime()) / 86_400_000)
  );

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      {/* Identity */}
      <Card className="p-6">
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-gradient-to-br from-sky-400 to-sky-600 grid place-items-center text-2xl font-bold text-white shrink-0">
            {userInitial(user)}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold text-zinc-900 dark:text-white">{name}</h1>
              <span
                className={cn(
                  "px-2 py-0.5 rounded-full text-[11px] font-semibold border flex items-center gap-1",
                  TIER_STYLE[user.tier]
                )}
              >
                <Crown size={11} /> {user.tier}
              </span>
            </div>
            <p className="text-sm text-zinc-500 truncate">{user.email}</p>
            <p className="text-xs text-zinc-400 dark:text-zinc-600 mt-1">
              Member since{" "}
              {memberSince.toLocaleDateString("en-US", {
                year: "numeric",
                month: "short",
                day: "numeric",
              })}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 mt-5">
          <Stat label="Watchlist" value={tickers.length} />
          <Stat label="Plan" value={user.tier} />
          <Stat label="Member for" value={`${memberDays}d`} accent />
        </div>
      </Card>

      {/* Plan */}
      <Card className="p-5">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <Shield size={18} className="text-sky-500 dark:text-sky-400 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                Current plan: {user.tier}
              </p>
              <p className="text-xs text-zinc-500">
                Top-100 daily signals · upgrade for full 2,000-stock real-time coverage
              </p>
            </div>
          </div>
          {user.tier === "FREE" && (
            <button className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-sky-500 to-sky-600 hover:from-sky-400 hover:to-sky-500 text-white text-sm font-semibold transition-colors">
              Upgrade
            </button>
          )}
        </div>
      </Card>

      {/* Watchlist */}
      <Card className="p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200 flex items-center gap-2">
            <Star size={15} className="text-amber-500 dark:text-amber-400" /> My Watchlist
          </h2>
          <Link
            href="/screener"
            className="text-xs text-zinc-500 hover:text-sky-600 dark:hover:text-sky-400 transition-colors"
          >
            Browse universe
          </Link>
        </div>
        {tickers.length === 0 ? (
          <p className="text-xs text-zinc-400 dark:text-zinc-600 py-4 text-center">
            No tickers yet ·{" "}
            <Link href="/screener" className="text-sky-600 dark:text-sky-400 hover:underline">
              browse the screener
            </Link>
          </p>
        ) : (
          <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {tickers.slice(0, 8).map((t) => {
              const sig = signalByTicker[t];
              return (
                <Link
                  key={t}
                  href={`/signals/${t}`}
                  className="flex items-center justify-between py-2.5 -mx-2 px-2 rounded-md hover:bg-zinc-100 dark:hover:bg-zinc-800/30 transition-colors"
                >
                  <span className="font-mono font-semibold text-sm text-zinc-800 dark:text-zinc-200">
                    {t}
                  </span>
                  {sig ? (
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-mono text-zinc-600 dark:text-zinc-400">
                        {Math.round(sig.confidence * 100)}%
                      </span>
                      <DirectionBadge direction={sig.direction} />
                    </div>
                  ) : (
                    <span className="text-xs text-zinc-400 dark:text-zinc-600">no signal yet</span>
                  )}
                </Link>
              );
            })}
          </div>
        )}
      </Card>

      {/* Settings */}
      <Card className="p-2">
        <SettingRow icon={Bell} label="Notifications" sub="Signal alerts & price moves — coming soon" disabled />
        <SettingRow icon={Settings} label="Preferences" sub="Theme, default holding period — coming soon" disabled />
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-3 py-3 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors text-left"
        >
          <LogOut size={17} className="text-red-500 dark:text-red-400" />
          <p className="text-sm font-medium text-red-500 dark:text-red-400">Sign out</p>
        </button>
      </Card>
    </div>
  );
}

function SettingRow({
  icon: Icon,
  label,
  sub,
  disabled,
}: {
  icon: typeof Bell;
  label: string;
  sub: string;
  disabled?: boolean;
}) {
  return (
    <div
      className={cn(
        "w-full flex items-center gap-3 px-3 py-3 rounded-lg text-left",
        disabled ? "opacity-60 cursor-not-allowed" : "hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
      )}
    >
      <Icon size={17} className="text-zinc-600 dark:text-zinc-400" />
      <div className="flex-1">
        <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{label}</p>
        <p className="text-xs text-zinc-500">{sub}</p>
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: ReactNode; accent?: boolean }) {
  return (
    <div className="rounded-lg bg-zinc-100 dark:bg-zinc-800/40 p-3 text-center">
      <p
        className={cn(
          "text-lg font-bold font-mono",
          accent ? "text-emerald-600 dark:text-emerald-400" : "text-zinc-800 dark:text-zinc-200"
        )}
      >
        {value}
      </p>
      <p className="text-[11px] text-zinc-500 mt-0.5">{label}</p>
    </div>
  );
}
