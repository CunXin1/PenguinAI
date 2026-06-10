"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { auth } from "@/lib/api";

// Apple Sign In needs a paid Apple Developer account + an HTTPS domain, so the
// button stays hidden until NEXT_PUBLIC_APPLE_OAUTH_ENABLED=true.
const APPLE_OAUTH_ENABLED = process.env.NEXT_PUBLIC_APPLE_OAUTH_ENABLED === "true";

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
  const [username, setUsername] = useState("");
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
      errors.email = mode === "login" ? "Email or username is required" : "Email is required";
    } else if (mode === "register" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      errors.email = "Enter a valid email address";
    }

    if (mode === "register") {
      if (!/^[A-Za-z0-9_]{3,20}$/.test(username.trim())) {
        errors.username = "3-20 characters: letters, numbers, or underscore";
      }
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
      const identifier = email.trim();
      const res =
        mode === "login"
          ? await auth.login(identifier, password)
          : await auth.register(identifier.toLowerCase(), password, username.trim());

      localStorage.setItem("access_token", res.access_token);
      if (mode === "register") {
        router.push("/auth/verify-pending");
      } else {
        // ADMIN users go straight to the admin dashboard
        try {
          const me = await auth.me();
          router.push(me.tier === "ADMIN" ? "/admin" : "/");
        } catch {
          router.push("/");
        }
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

  const startOAuth = (provider: "google" | "apple") => {
    // Full-page navigation — the backend 302s to the provider and back to /auth/callback.
    window.location.href = auth.oauthStartUrl(provider);
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
                label="Username"
                type="text"
                value={username}
                onChange={(v) => { setUsername(v); setFieldErrors((e) => ({ ...e, username: "" })); }}
                placeholder="your_handle"
                required
                error={fieldErrors.username}
                autoComplete="username"
              />
            )}

            <Field
              label={mode === "login" ? "Email or username" : "Email"}
              type={mode === "login" ? "text" : "email"}
              value={email}
              onChange={(v) => { setEmail(v); setFieldErrors((e) => ({ ...e, email: "" })); }}
              placeholder={mode === "login" ? "you@example.com or your_handle" : "you@example.com"}
              required
              error={fieldErrors.email}
              autoComplete={mode === "login" ? "username" : "email"}
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

          {/* Divider */}
          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-zinc-200 dark:bg-zinc-700/60" />
            <span className="text-[11px] uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
              or
            </span>
            <div className="h-px flex-1 bg-zinc-200 dark:bg-zinc-700/60" />
          </div>

          {/* OAuth providers */}
          <div className="space-y-2.5">
            <button
              type="button"
              onClick={() => startOAuth("google")}
              className="w-full flex items-center justify-center gap-2.5 py-2.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white hover:bg-zinc-50 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-900 dark:text-white text-sm font-medium transition-colors"
            >
              <GoogleIcon />
              Continue with Google
            </button>
            {APPLE_OAUTH_ENABLED && (
              <button
                type="button"
                onClick={() => startOAuth("apple")}
                className="w-full flex items-center justify-center gap-2.5 py-2.5 rounded-lg bg-black hover:bg-zinc-900 text-white text-sm font-medium transition-colors"
              >
                <AppleIcon />
                Continue with Apple
              </button>
            )}
          </div>

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

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5h-1.9V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.3-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16 19 13 24 13c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.6 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H24v8h11.3c-.8 2.2-2.2 4.1-4.1 5.6l6.2 5.2C41.4 36.4 44 30.7 44 24c0-1.3-.1-2.3-.4-3.5z" />
    </svg>
  );
}

function AppleIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 384 512" fill="currentColor" aria-hidden="true">
      <path d="M318.7 268c-.3-37 16.4-65 50.1-85.7-18.8-27-47.3-41.8-84.8-44.7-35.5-2.8-74.3 20.7-88.5 20.7-15 0-49.4-19.7-76.4-19.7C71.3 139.5 18 184.4 18 273.5c0 26.3 4.8 53.5 14.4 81.5 12.8 36.8 59 127 107.2 125.5 25.2-.6 43-17.9 75.8-17.9 31.8 0 48.3 17.9 76.4 17.9 48.6-.7 90.4-82.5 102.6-119.4-65.2-30.7-61.7-90-61.7-91.6zm-56.6-164c27.3-32.4 24.8-61.9 24-72.5-24.1 1.4-52 16.4-67.9 34.9-17.5 19.8-27.8 44.3-25.6 71.9 26.1 2 49.9-11.4 69.5-34.3z" />
    </svg>
  );
}
