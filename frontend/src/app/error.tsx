"use client";

import Link from "next/link";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-[calc(100vh-3.5rem)] flex flex-col items-center justify-center px-4 text-center">
      <h1 className="text-2xl font-bold text-white">Something went wrong</h1>
      <p className="mt-2 text-sm text-zinc-400">An unexpected error occurred.</p>
      {process.env.NODE_ENV === "development" ? (
        <pre className="mt-4 max-w-lg overflow-x-auto rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-3 text-left text-xs text-zinc-400">
          {error.message}
        </pre>
      ) : error.digest ? (
        <p className="mt-4 text-xs text-zinc-500">Error ID: {error.digest}</p>
      ) : null}
      <div className="mt-8 flex gap-3">
        <button
          onClick={reset}
          className="rounded-lg bg-sky-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-sky-400 transition-colors"
        >
          Try again
        </button>
        <Link
          href="/"
          className="rounded-lg border border-zinc-700 px-5 py-2.5 text-sm font-semibold text-zinc-300 hover:border-zinc-500 transition-colors"
        >
          Go home
        </Link>
      </div>
    </div>
  );
}
