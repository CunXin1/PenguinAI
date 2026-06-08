"use client";

import { Suspense, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react";
import { auth } from "@/lib/api";

interface PasswordCheck {
  label: string;
  test: (p: string) => boolean;
}

const PASSWORD_CHECKS: PasswordCheck[] = [
  { label: "8+ characters", test: (p) => p.length >= 8 },
  { label: "Uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { label: "Lowercase letter", test: (p) => /[a-z]/.test(p) },
  { label: "Number", test: (p) => /\d/.test(p) },
  { label: "Special character", test: (p) => /[^A-Za-z0-9]/.test(p) },
];

function getStrength(password: string) {
  const passed = PASSWORD_CHECKS.filter((c) => c.test(password)).length;
  if (passed <= 2) return { score: passed, label: "Weak", color: "bg-red-500" };
  if (passed <= 3) return { score: passed, label: "Fair", color: "bg-amber-500" };
  if (passed <= 4) return { score: passed, label: "Good", color: "bg-sky-500" };
  return { score: passed, label: "Strong", color: "bg-emerald-500" };
}

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const strength = useMemo(() => getStrength(password), [password]);

  const validate = (): boolean => {
    const errors: Record<string, string> = {};
    if (strength.score < 5) errors.password = "Password does not meet all requirements";
    if (confirmPassword !== password) errors.confirmPassword = "Passwords do not match";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!validate()) return;
    setLoading(true);

    try {
      await auth.resetPassword(token!, password);
      setSuccess(true);
      setTimeout(() => router.push("/auth/login"), 3000);
    } catch (err: any) {
      const detail = err?.data?.detail;
      if (typeof detail === "string") {
        setError(detail);
      } else if (Array.isArray(detail)) {
        const msgs = detail.map((d: any) => d.msg?.replace(/^Value error, /, "") ?? "").filter(Boolean);
        setError(msgs.join(". ") || "Validation failed");
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <div className="text-center space-y-4 py-2">
        <h2 className="text-base font-semibold text-zinc-900 dark:text-white">
          Invalid reset link
        </h2>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          This password reset link is invalid or has expired. Please request a new one.
        </p>
        <Link
          href="/auth/forgot-password"
          className="inline-flex items-center gap-1.5 text-sm text-sky-500 hover:text-sky-400 transition-colors"
        >
          Request new reset link
        </Link>
      </div>
    );
  }

  if (success) {
    return (
      <div className="text-center space-y-4 py-2">
        <div className="w-12 h-12 rounded-full bg-emerald-500/10 grid place-items-center mx-auto">
          <CheckCircle2 size={22} className="text-emerald-500" />
        </div>
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-zinc-900 dark:text-white">
            Password reset successful
          </h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Redirecting you to sign in...
          </p>
        </div>
        <Link
          href="/auth/login"
          className="inline-flex items-center gap-1.5 text-sm text-sky-500 hover:text-sky-400 transition-colors"
        >
          <ArrowLeft size={14} />
          Sign in now
        </Link>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-zinc-900 dark:text-white">
          Set new password
        </h2>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Choose a strong password for your account.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {/* New password */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            New password
          </label>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => { setPassword(e.target.value); setFieldErrors((fe) => ({ ...fe, password: "" })); }}
              placeholder="••••••••"
              required
              autoComplete="new-password"
              autoFocus
              className={`w-full rounded-lg bg-zinc-100 dark:bg-zinc-800 border px-3 py-2.5 pr-10 text-sm text-zinc-900 dark:text-white placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none transition-colors ${
                fieldErrors.password
                  ? "border-red-500/60 focus:border-red-500"
                  : "border-zinc-200 dark:border-zinc-700 focus:border-sky-500"
              }`}
            />
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              tabIndex={-1}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          {fieldErrors.password && (
            <p className="text-xs text-red-500 dark:text-red-400">{fieldErrors.password}</p>
          )}

          {password.length > 0 && (
            <div className="space-y-2 pt-1">
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 rounded-full bg-zinc-200 dark:bg-zinc-700 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${strength.color}`}
                    style={{ width: `${(strength.score / 5) * 100}%` }}
                  />
                </div>
                <span className={`text-xs font-medium ${
                  strength.score <= 2 ? "text-red-500" :
                  strength.score <= 3 ? "text-amber-500" :
                  strength.score <= 4 ? "text-sky-500" : "text-emerald-500"
                }`}>
                  {strength.label}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                {PASSWORD_CHECKS.map((c) => {
                  const ok = c.test(password);
                  return (
                    <span
                      key={c.label}
                      className={`text-[11px] transition-colors ${
                        ok ? "text-emerald-500" : "text-zinc-400 dark:text-zinc-500"
                      }`}
                    >
                      {ok ? "✓" : "•"} {c.label}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Confirm password */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            Confirm new password
          </label>
          <div className="relative">
            <input
              type={showConfirm ? "text" : "password"}
              value={confirmPassword}
              onChange={(e) => { setConfirmPassword(e.target.value); setFieldErrors((fe) => ({ ...fe, confirmPassword: "" })); }}
              placeholder="••••••••"
              required
              autoComplete="new-password"
              className={`w-full rounded-lg bg-zinc-100 dark:bg-zinc-800 border px-3 py-2.5 pr-10 text-sm text-zinc-900 dark:text-white placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none transition-colors ${
                fieldErrors.confirmPassword
                  ? "border-red-500/60 focus:border-red-500"
                  : "border-zinc-200 dark:border-zinc-700 focus:border-sky-500"
              }`}
            />
            <button
              type="button"
              onClick={() => setShowConfirm((s) => !s)}
              tabIndex={-1}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
            >
              {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          {fieldErrors.confirmPassword && (
            <p className="text-xs text-red-500 dark:text-red-400">{fieldErrors.confirmPassword}</p>
          )}
        </div>

        {error && (
          <p className="text-sm text-red-600 dark:text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm transition-colors flex items-center justify-center gap-2"
        >
          {loading && <Loader2 size={16} className="animate-spin" />}
          {loading ? "Resetting..." : "Reset password"}
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
  );
}

export default function ResetPasswordPage() {
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
          <Suspense fallback={
            <div className="flex items-center justify-center py-8">
              <Loader2 size={20} className="animate-spin text-zinc-400" />
            </div>
          }>
            <ResetPasswordForm />
          </Suspense>
        </div>

        <p className="text-center text-xs text-zinc-400 dark:text-zinc-600">
          Signal platform &middot; No trading execution
        </p>
      </div>
    </main>
  );
}
