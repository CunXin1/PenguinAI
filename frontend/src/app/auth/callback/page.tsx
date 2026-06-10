"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Loader2, AlertCircle } from "lucide-react";
import { auth } from "@/lib/api";

const ERROR_MESSAGES: Record<string, string> = {
  oauth_unavailable: "This sign-in method isn't available right now.",
  oauth_cancelled: "Sign-in was cancelled.",
  invalid_state: "Your sign-in session expired. Please try again.",
  oauth_failed: "We couldn't complete sign-in. Please try again.",
  oauth_no_email: "Your provider didn't share an email address with us.",
};

/**
 * OAuth landing page. The backend redirects here with the result in the URL
 * fragment (`#access_token=...` or `#error=...`) so the token never hits a
 * server log or the Referer header.
 */
export default function OAuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "";
    const params = new URLSearchParams(hash);
    const token = params.get("access_token");
    const err = params.get("error");

    // Strip the fragment so the token isn't left in history / on screen.
    window.history.replaceState(null, "", window.location.pathname);

    if (err || !token) {
      setError(ERROR_MESSAGES[err ?? ""] ?? "Sign-in failed. Please try again.");
      return;
    }

    localStorage.setItem("access_token", token);
    (async () => {
      try {
        const me = await auth.me();
        router.replace(me.tier === "ADMIN" ? "/admin" : "/");
      } catch {
        router.replace("/");
      }
    })();
  }, [router]);

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm text-center space-y-4">
        {error ? (
          <>
            <div className="flex justify-center">
              <AlertCircle className="text-red-500" size={32} />
            </div>
            <p className="text-sm text-zinc-300">{error}</p>
            <Link
              href="/auth/login"
              className="inline-block text-sm font-medium text-sky-400 hover:text-sky-300 transition-colors"
            >
              Back to sign in
            </Link>
          </>
        ) : (
          <>
            <div className="flex justify-center">
              <Loader2 className="animate-spin text-sky-400" size={32} />
            </div>
            <p className="text-sm text-zinc-400">Completing sign-in…</p>
          </>
        )}
      </div>
    </main>
  );
}
