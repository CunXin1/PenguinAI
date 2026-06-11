"use client";

import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Crown,
  Sparkles,
  Bot,
  BrainCircuit,
  BellRing,
  Rocket,
  Loader2,
  CheckCircle2,
  Ticket,
} from "lucide-react";
import { Card } from "@/components/ui/Card";
import { useAuth } from "@/hooks/useAuth";
import { billing } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { UserTier } from "@/lib/types";

const PRO_PRICE = 10;

// A paid-tier (PRO/PREMIUM/ADMIN) account already has everything the Pro card sells.
const PAID_TIERS: UserTier[] = ["PRO", "PREMIUM", "ADMIN"];

type Feature = { icon: typeof Bot; label: string; sub?: string };

const FREE_FEATURES: Feature[] = [
  { icon: Check, label: "Top-100 daily signals" },
  { icon: Check, label: "Watchlist & screener" },
  { icon: Check, label: "Earnings, FOMC & celebrity holdings" },
  { icon: Bot, label: "AI assistant", sub: "5 messages / 5 hours" },
];

const PRO_FEATURES: Feature[] = [
  { icon: Bot, label: "Much higher AI chat limits", sub: "20× the free allowance" },
  { icon: BrainCircuit, label: "Train your own stock ML models", sub: "tune signals on tickers you pick" },
  { icon: BellRing, label: "AI custom notifications", sub: "alerts on the moves you care about" },
  { icon: Rocket, label: "More premium features coming", sub: "early access as they ship" },
];

export default function PricingPage() {
  const { user, isLoggedIn } = useAuth();
  const isPaid = !!user && PAID_TIERS.includes(user.tier);

  return (
    <div className="max-w-5xl mx-auto px-4 py-10 space-y-10">
      {/* Header */}
      <div className="text-center space-y-3">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-sky-500/10 border border-sky-500/30 text-xs font-semibold text-sky-600 dark:text-sky-400">
          <Sparkles size={13} /> Plans
        </div>
        <h1 className="text-3xl font-bold text-zinc-900 dark:text-white">
          Simple, honest pricing
        </h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 max-w-md mx-auto">
          Start free. Upgrade to Pro for deeper AI, your own trained models, and custom alerts.
        </p>
      </div>

      {/* Plan cards */}
      <div className="grid md:grid-cols-2 gap-5 items-start">
        {/* Free */}
        <Card className="p-6 space-y-5">
          <div className="space-y-1">
            <h2 className="text-lg font-bold text-zinc-900 dark:text-white">Free</h2>
            <p className="text-xs text-zinc-500">For getting started</p>
          </div>
          <div className="flex items-end gap-1">
            <span className="text-4xl font-bold text-zinc-900 dark:text-white">$0</span>
            <span className="text-sm text-zinc-500 mb-1.5">/ forever</span>
          </div>
          <FeatureList features={FREE_FEATURES} muted />
          <div className="pt-1">
            {!isLoggedIn ? (
              <Link
                href="/auth/login"
                className="block w-full text-center px-4 py-2.5 rounded-lg border border-zinc-300 dark:border-zinc-700 text-sm font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors"
              >
                Get started
              </Link>
            ) : (
              <div className="w-full text-center px-4 py-2.5 rounded-lg bg-zinc-100 dark:bg-zinc-800/50 text-sm font-semibold text-zinc-500">
                {isPaid ? "Included" : "Your current plan"}
              </div>
            )}
          </div>
        </Card>

        {/* Pro */}
        <Card className="p-6 space-y-5 border-sky-500/50 dark:border-sky-500/40 relative overflow-hidden">
          <div className="absolute top-0 right-0 px-3 py-1 rounded-bl-lg bg-gradient-to-r from-sky-500 to-sky-600 text-[11px] font-bold text-white">
            POPULAR
          </div>
          <div className="space-y-1">
            <h2 className="text-lg font-bold text-zinc-900 dark:text-white flex items-center gap-2">
              <Crown size={18} className="text-amber-500 dark:text-amber-400" /> Pro
            </h2>
            <p className="text-xs text-zinc-500">For serious traders</p>
          </div>
          <div className="flex items-end gap-1">
            <span className="text-4xl font-bold text-zinc-900 dark:text-white">${PRO_PRICE}</span>
            <span className="text-sm text-zinc-500 mb-1.5">/ month</span>
          </div>
          <FeatureList features={PRO_FEATURES} />
          <div className="pt-1">
            {isPaid ? (
              <div className="w-full text-center px-4 py-2.5 rounded-lg bg-sky-500/10 border border-sky-500/40 text-sm font-semibold text-sky-600 dark:text-sky-400 flex items-center justify-center gap-2">
                <CheckCircle2 size={16} /> You&apos;re on {user!.tier}
              </div>
            ) : (
              <ComingSoonButton />
            )}
          </div>
        </Card>
      </div>

      {/* Invite code redemption */}
      <RedeemCard isLoggedIn={isLoggedIn} alreadyPaid={isPaid} />

      <p className="text-center text-xs text-zinc-400 dark:text-zinc-600">
        Signals are research, not financial advice. PenguinAI never executes trades.
      </p>
    </div>
  );
}

function FeatureList({ features, muted }: { features: Feature[]; muted?: boolean }) {
  return (
    <ul className="space-y-2.5">
      {features.map(({ icon: Icon, label, sub }) => (
        <li key={label} className="flex items-start gap-2.5">
          <Icon
            size={16}
            className={cn(
              "mt-0.5 shrink-0",
              muted ? "text-zinc-400 dark:text-zinc-500" : "text-sky-500 dark:text-sky-400"
            )}
          />
          <div>
            <p className="text-sm text-zinc-800 dark:text-zinc-200 leading-tight">{label}</p>
            {sub && <p className="text-xs text-zinc-500 mt-0.5">{sub}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** The checkout button — payment is not wired yet, so it advertises "Coming Soon". */
function ComingSoonButton() {
  return (
    <div className="space-y-1.5">
      <button
        type="button"
        disabled
        className="w-full px-4 py-2.5 rounded-lg bg-gradient-to-r from-sky-500/60 to-sky-600/60 text-white text-sm font-semibold cursor-not-allowed opacity-80"
      >
        Subscribe — Coming Soon
      </button>
      <p className="text-center text-[11px] text-zinc-400 dark:text-zinc-600">
        Online payment isn&apos;t live yet. Have an invite code? Redeem it below.
      </p>
    </div>
  );
}

function RedeemCard({
  isLoggedIn,
  alreadyPaid,
}: {
  isLoggedIn: boolean;
  alreadyPaid: boolean;
}) {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleRedeem = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = code.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await billing.redeem(trimmed);
      setSuccess(res.message);
      setCode("");
      // Tier changed server-side — refresh the cached /me so the whole app updates.
      await qc.invalidateQueries({ queryKey: ["me"] });
    } catch (err: unknown) {
      const detail = (err as { data?: { detail?: string } })?.data?.detail;
      setError(typeof detail === "string" ? detail : "Could not redeem this code.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="p-6 max-w-xl mx-auto">
      <div className="flex items-center gap-2 mb-1">
        <Ticket size={17} className="text-amber-500 dark:text-amber-400" />
        <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
          Have an invite code?
        </h3>
      </div>
      <p className="text-xs text-zinc-500 mb-4">
        Redeem a code to unlock Pro instantly.
      </p>

      {!isLoggedIn ? (
        <Link
          href="/auth/login"
          className="block w-full text-center px-4 py-2.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-white text-sm font-semibold transition-colors"
        >
          Sign in to redeem
        </Link>
      ) : success ? (
        <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-3 py-2.5">
          <CheckCircle2 size={16} className="shrink-0" />
          {success}
        </div>
      ) : (
        <form onSubmit={handleRedeem} className="space-y-2.5">
          <div className="flex gap-2">
            <input
              value={code}
              onChange={(e) => {
                setCode(e.target.value);
                setError(null);
              }}
              placeholder="Enter invite code"
              autoComplete="off"
              spellCheck={false}
              className="flex-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 px-3 py-2.5 text-sm text-zinc-900 dark:text-white placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none focus:border-sky-500 transition-colors font-mono"
            />
            <button
              type="submit"
              disabled={loading || !code.trim()}
              className="px-4 py-2.5 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors flex items-center gap-2 shrink-0"
            >
              {loading && <Loader2 size={15} className="animate-spin" />}
              {loading ? "Redeeming" : "Redeem"}
            </button>
          </div>
          {error && (
            <p className="text-sm text-red-600 dark:text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
          {alreadyPaid && (
            <p className="text-[11px] text-zinc-400 dark:text-zinc-600">
              You already have a paid plan — redeeming a higher-tier code still works.
            </p>
          )}
        </form>
      )}
    </Card>
  );
}
