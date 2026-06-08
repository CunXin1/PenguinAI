"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { auth } from "@/lib/api";

function VerifyEmailForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setErrorMsg("Missing verification token.");
      return;
    }

    let cancelled = false;
    auth
      .verifyEmail(token)
      .then(() => {
        if (!cancelled) setStatus("success");
        setTimeout(() => router.push("/auth/login"), 3000);
      })
      .catch((err: any) => {
        if (cancelled) return;
        setStatus("error");
        setErrorMsg(
          typeof err?.data?.detail === "string"
            ? err.data.detail
            : "Verification failed. The link may be expired."
        );
      });

    return () => { cancelled = true; };
  }, [token, router]);

  if (status === "loading") {
    return (
      <div className="text-center space-y-4 py-6">
        <Loader2 size={28} className="animate-spin text-sky-500 mx-auto" />
        <p className="text-sm text-zinc-500 dark:text-zinc-400">Verifying your email...</p>
      </div>
    );
  }

  if (status === "success") {
    return (
      <div className="text-center space-y-4 py-2">
        <div className="w-12 h-12 rounded-full bg-emerald-500/10 grid place-items-center mx-auto">
          <CheckCircle2 size={22} className="text-emerald-500" />
        </div>
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-zinc-900 dark:text-white">
            Email verified
          </h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Your account is now fully activated. Redirecting to sign in...
          </p>
        </div>
        <Link
          href="/auth/login"
          className="inline-flex text-sm text-sky-500 hover:text-sky-400 transition-colors"
        >
          Sign in now
        </Link>
      </div>
    );
  }

  return (
    <div className="text-center space-y-4 py-2">
      <div className="w-12 h-12 rounded-full bg-red-500/10 grid place-items-center mx-auto">
        <XCircle size={22} className="text-red-500" />
      </div>
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-zinc-900 dark:text-white">
          Verification failed
        </h2>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">{errorMsg}</p>
      </div>
      <div className="flex flex-col gap-2 items-center">
        <Link
          href="/auth/verify-pending"
          className="text-sm text-sky-500 hover:text-sky-400 transition-colors"
        >
          Resend verification email
        </Link>
        <Link
          href="/auth/login"
          className="text-xs text-zinc-400 hover:text-zinc-300 transition-colors"
        >
          Back to sign in
        </Link>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold">
            <span className="text-zinc-900 dark:text-white">Penguin</span>
            <span className="text-sky-500 dark:text-sky-400">AI</span>
          </h1>
          <p className="text-zinc-500 text-sm mt-1">AI Quantitative Signal Platform</p>
        </div>

        <div className="rounded-xl border border-zinc-200 dark:border-zinc-700/60 bg-white dark:bg-zinc-900 p-6 space-y-5">
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-8">
                <Loader2 size={20} className="animate-spin text-zinc-400" />
              </div>
            }
          >
            <VerifyEmailForm />
          </Suspense>
        </div>

        <p className="text-center text-xs text-zinc-400 dark:text-zinc-600">
          Signal platform &middot; No trading execution
        </p>
      </div>
    </main>
  );
}
