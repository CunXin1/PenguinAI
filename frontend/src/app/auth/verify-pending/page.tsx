"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, Mail, RefreshCw } from "lucide-react";
import { auth } from "@/lib/api";

// Set by the login/register page before redirecting here. The user has no
// session yet (hard verification), so the email can't come from /me.
const PENDING_EMAIL_KEY = "penguinai_pending_verify_email";

export default function VerifyPendingPage() {
  const [email, setEmail] = useState<string | null>(null);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  useEffect(() => {
    setEmail(sessionStorage.getItem(PENDING_EMAIL_KEY));
  }, []);

  const handleResend = async () => {
    if (!email) return;
    setResending(true);
    try {
      await auth.resendVerification(email);
      setResent(true);
      setTimeout(() => setResent(false), 10000);
    } catch {
      // Anti-enumeration endpoint always succeeds; nothing to surface.
    } finally {
      setResending(false);
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
          <div className="text-center space-y-4 py-2">
            <div className="w-12 h-12 rounded-full bg-sky-500/10 grid place-items-center mx-auto">
              <Mail size={22} className="text-sky-500" />
            </div>
            <div className="space-y-1">
              <h2 className="text-base font-semibold text-zinc-900 dark:text-white">
                Verify your email
              </h2>
              <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                We sent a verification link to{" "}
                {email ? (
                  <span className="font-medium text-zinc-700 dark:text-zinc-300">{email}</span>
                ) : (
                  "your email"
                )}
                . Click the link to activate your account, then sign in.
              </p>
            </div>

            <div className="space-y-3 pt-2">
              {email && (
                <button
                  onClick={handleResend}
                  disabled={resending || resent}
                  className="w-full py-2.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-sm font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                >
                  {resending ? (
                    <><Loader2 size={15} className="animate-spin" /> Sending...</>
                  ) : resent ? (
                    "Email sent! Check your inbox"
                  ) : (
                    <><RefreshCw size={15} /> Resend verification email</>
                  )}
                </button>
              )}

              <Link
                href="/auth/login"
                className="inline-flex items-center justify-center gap-1.5 w-full py-2.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-white font-semibold text-sm text-center transition-colors"
              >
                <ArrowLeft size={14} />
                Back to sign in
              </Link>
            </div>

            <p className="text-[11px] text-zinc-400 dark:text-zinc-500 leading-relaxed">
              You must verify your email before you can sign in. The link expires in 24 hours.
            </p>
          </div>
        </div>

        <p className="text-center text-xs text-zinc-400 dark:text-zinc-600">
          Signal platform &middot; No trading execution
        </p>
      </div>
    </main>
  );
}
