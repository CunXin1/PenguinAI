"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="bg-zinc-950 text-white">
        <div className="min-h-screen flex flex-col items-center justify-center px-4 text-center">
          <h1 className="text-2xl font-bold">Something went wrong</h1>
          <p className="mt-2 text-sm text-zinc-400">A critical error occurred.</p>
          <pre className="mt-4 max-w-lg overflow-x-auto rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-3 text-left text-xs text-zinc-400">
            {error.message}
          </pre>
          <div className="mt-8 flex gap-3">
            <button
              onClick={reset}
              className="rounded-lg bg-sky-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-sky-400 transition-colors"
            >
              Try again
            </button>
            <a
              href="/"
              className="rounded-lg border border-zinc-700 px-5 py-2.5 text-sm font-semibold text-zinc-300 hover:border-zinc-500 transition-colors"
            >
              Go home
            </a>
          </div>
        </div>
      </body>
    </html>
  );
}
