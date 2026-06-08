import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-[calc(100vh-3.5rem)] flex flex-col items-center justify-center px-4 text-center">
      <h1 className="text-7xl font-bold text-white">404</h1>
      <h2 className="mt-4 text-xl font-semibold text-zinc-300">Page not found</h2>
      <p className="mt-2 max-w-md text-sm text-zinc-400">
        The page you&apos;re looking for doesn&apos;t exist or has been moved.
      </p>
      <div className="mt-8 flex gap-3">
        <Link
          href="/"
          className="rounded-lg bg-sky-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-sky-400 transition-colors"
        >
          Go home
        </Link>
        <Link
          href="/screener"
          className="rounded-lg border border-zinc-700 px-5 py-2.5 text-sm font-semibold text-zinc-300 hover:border-zinc-500 transition-colors"
        >
          Search stocks
        </Link>
      </div>
    </div>
  );
}
