"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, Mail } from "lucide-react";
import { auth } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError("Enter a valid email address");
      return;
    }

    setLoading(true);
    try {
      await auth.forgotPassword(email.trim().toLowerCase());
      setSent(true);
    } catch {
      setSent(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo */}
        <div className="text-center">
          <h1 className="text-3xl font-bold">
            <span className="text-zinc-900 dark:text-white">Penguin</span>
            <span className="text-sky-500 dark:text-sky-400">AI</span>
          </h1>
          <p className="text-zinc-500 text-sm mt-1">AI Quantitative Signal Platform</p>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-700/60 bg-white dark:bg-zinc-900 p-6 space-y-5">
          {sent ? (
            <div className="text-center space-y-4 py-2">
              <div className="w-12 h-12 rounded-full bg-sky-500/10 grid place-items-center mx-auto">
                <Mail size={22} className="text-sky-500" />
              </div>
              <div className="space-y-1">
                <h2 className="text-base font-semibold text-zinc-900 dark:text-white">
                  Check your email
                </h2>
                <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                  If <span className="font-medium text-zinc-700 dark:text-zinc-300">{email}</span> is
                  registered, we sent a password reset link. Check your inbox and spam folder.
                </p>
              </div>
              <Link
                href="/auth/login"
                className="inline-flex items-center gap-1.5 text-sm text-sky-500 hover:text-sky-400 transition-colors"
              >
                <ArrowLeft size={14} />
                Back to sign in
              </Link>
            </div>
          ) : (
            <>
              <div className="space-y-1">
                <h2 className="text-base font-semibold text-zinc-900 dark:text-white">
                  Reset your password
                </h2>
                <p className="text-sm text-zinc-500 dark:text-zinc-400">
                  Enter your email and we&apos;ll send you a reset link.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4" noValidate>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                    Email
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => { setEmail(e.target.value); setError(null); }}
                    placeholder="you@example.com"
                    required
                    autoComplete="email"
                    autoFocus
                    className={`w-full rounded-lg bg-zinc-100 dark:bg-zinc-800 border px-3 py-2.5 text-sm text-zinc-900 dark:text-white placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none transition-colors ${
                      error
                        ? "border-red-500/60 focus:border-red-500"
                        : "border-zinc-200 dark:border-zinc-700 focus:border-sky-500"
                    }`}
                  />
                  {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm transition-colors flex items-center justify-center gap-2"
                >
                  {loading && <Loader2 size={16} className="animate-spin" />}
                  {loading ? "Sending..." : "Send reset link"}
                </button>
              </form>

              <div className="text-center">
                <Link
                  href="/auth/login"
                  className="inline-flex items-center gap-1.5 text-xs text-sky-500 hover:text-sky-400 transition-colors"
                >
                  <ArrowLeft size={12} />
                  Back to sign in
                </Link>
              </div>
            </>
          )}
        </div>

        <p className="text-center text-xs text-zinc-400 dark:text-zinc-600">
          Signal platform &middot; No trading execution
        </p>
      </div>
    </main>
  );
}
