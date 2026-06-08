"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { auth } from "@/lib/api";

type Mode = "login" | "register";

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

function getStrength(password: string): { score: number; label: string; color: string } {
  const passed = PASSWORD_CHECKS.filter((c) => c.test(password)).length;
  if (passed <= 2) return { score: passed, label: "Weak", color: "bg-red-500" };
  if (passed <= 3) return { score: passed, label: "Fair", color: "bg-amber-500" };
  if (passed <= 4) return { score: passed, label: "Good", color: "bg-sky-500" };
  return { score: passed, label: "Strong", color: "bg-emerald-500" };
}

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) router.replace("/");
  }, [router]);

  const strength = useMemo(() => getStrength(password), [password]);

  const validate = (): boolean => {
    const errors: Record<string, string> = {};

    if (!email.trim()) {
      errors.email = "Email is required";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      errors.email = "Enter a valid email address";
    }

    if (mode === "register") {
      if (strength.score < 5) {
        errors.password = "Password does not meet all requirements";
      }
      if (confirmPassword !== password) {
        errors.confirmPassword = "Passwords do not match";
      }
    } else {
      if (!password) {
        errors.password = "Password is required";
      }
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!validate()) return;
    setLoading(true);

    try {
      const normalizedEmail = email.trim().toLowerCase();
      const res =
        mode === "login"
          ? await auth.login(normalizedEmail, password)
          : await auth.register(normalizedEmail, password, displayName.trim() || undefined);

      localStorage.setItem("access_token", res.access_token);
      if (mode === "register") {
        router.push("/auth/verify-pending");
      } else {
        router.push("/");
      }
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

  const switchMode = (m: Mode) => {
    setMode(m);
    setError(null);
    setFieldErrors({});
    setShowPassword(false);
    setShowConfirm(false);
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
          {/* Mode toggle */}
          <div className="flex rounded-lg bg-zinc-100 dark:bg-zinc-800 p-1">
            {(["login", "register"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => switchMode(m)}
                className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  mode === m
                    ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm"
                    : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                }`}
              >
                {m === "login" ? "Sign in" : "Sign up"}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {mode === "register" && (
              <Field
                label="Display name"
                type="text"
                value={displayName}
                onChange={(v) => { setDisplayName(v); setFieldErrors((e) => ({ ...e, displayName: "" })); }}
                placeholder="Optional"
              />
            )}

            <Field
              label="Email"
              type="email"
              value={email}
              onChange={(v) => { setEmail(v); setFieldErrors((e) => ({ ...e, email: "" })); }}
              placeholder="you@example.com"
              required
              error={fieldErrors.email}
              autoComplete="email"
            />

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setFieldErrors((fe) => ({ ...fe, password: "" })); }}
                  placeholder="••••••••"
                  required
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
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

              {/* Strength indicator (register only) */}
              {mode === "register" && password.length > 0 && (
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

            {/* Confirm password (register only) */}
            {mode === "register" && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  Confirm password
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
            )}

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
              {loading
                ? mode === "login" ? "Signing in..." : "Creating account..."
                : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          {/* Forgot password (login only) */}
          {mode === "login" && (
            <div className="text-center">
              <Link
                href="/auth/forgot-password"
                className="text-xs text-sky-500 hover:text-sky-400 transition-colors"
              >
                Forgot your password?
              </Link>
            </div>
          )}

          {/* Terms (register only) */}
          {mode === "register" && (
            <p className="text-[11px] text-zinc-400 dark:text-zinc-500 text-center leading-relaxed">
              By creating an account, you agree to our{" "}
              <span className="text-zinc-500 dark:text-zinc-400">Terms of Service</span> and{" "}
              <span className="text-zinc-500 dark:text-zinc-400">Privacy Policy</span>.
            </p>
          )}
        </div>

        <p className="text-center text-xs text-zinc-400 dark:text-zinc-600">
          Signal platform &middot; No trading execution
        </p>
      </div>
    </main>
  );
}

function Field({
  label,
  type,
  value,
  onChange,
  placeholder,
  required,
  error,
  autoComplete,
}: {
  label: string;
  type: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  error?: string;
  autoComplete?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        autoComplete={autoComplete}
        className={`w-full rounded-lg bg-zinc-100 dark:bg-zinc-800 border px-3 py-2.5 text-sm text-zinc-900 dark:text-white placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none transition-colors ${
          error
            ? "border-red-500/60 focus:border-red-500"
            : "border-zinc-200 dark:border-zinc-700 focus:border-sky-500"
        }`}
      />
      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
    </div>
  );
}
