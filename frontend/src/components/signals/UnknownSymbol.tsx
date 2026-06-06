"use client";

import { useState } from "react";
import Link from "next/link";
import { SearchX, Telescope, ArrowLeft, Check, Loader2, AlertCircle } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { symbolRequests } from "@/lib/api";

interface Props {
  symbol: string;
  /** Why there's no signal: not covered at all, or known-but-delisted. */
  reason?: "not_in_universe" | "delisted";
}

type ReqState = "idle" | "loading" | "done" | "error";

/**
 * In-place "we don't have this symbol" view for /signals/[ticker]. Distinct
 * from the demo fallback — it never fabricates a signal. For uncovered symbols
 * the user can log demand, which lands in the backend's symbol_requests queue.
 */
export function UnknownSymbol({ symbol, reason = "not_in_universe" }: Props) {
  const [state, setState] = useState<ReqState>("idle");
  const [msg, setMsg] = useState("");

  const delisted = reason === "delisted";

  const requestCoverage = async () => {
    setState("loading");
    try {
      const res = await symbolRequests.create(symbol);
      setMsg(res.message);
      setState("done");
    } catch {
      setMsg("Couldn't submit your request right now — please try again later.");
      setState("error");
    }
  };

  return (
    <div className="max-w-xl mx-auto px-4 py-10 sm:py-16">
      <Link
        href="/"
        className="text-sm text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 flex items-center gap-1 w-fit transition-colors mb-6"
      >
        <ArrowLeft size={14} /> Dashboard
      </Link>

      <Card className="p-8 text-center">
        <div className="w-14 h-14 mx-auto rounded-full bg-zinc-100 dark:bg-zinc-800 grid place-items-center text-zinc-400 dark:text-zinc-500">
          <SearchX size={26} />
        </div>

        <h1 className="mt-5 text-2xl font-bold font-mono text-zinc-900 dark:text-white">
          {symbol}
        </h1>

        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed">
          {delisted ? (
            <>
              <span className="font-medium text-zinc-800 dark:text-zinc-200">{symbol}</span>{" "}
              is delisted or no longer active, so there&apos;s no live signal for it.
            </>
          ) : (
            <>
              We don&apos;t cover{" "}
              <span className="font-medium text-zinc-800 dark:text-zinc-200">{symbol}</span> yet.
              It may be a delisted ticker, an OTC/penny stock, or not a valid US
              symbol — double-check the spelling.
            </>
          )}
        </p>

        {/* Request-coverage action — only for genuinely uncovered symbols */}
        {!delisted && (
          <div className="mt-6">
            {state === "done" ? (
              <div className="flex items-center justify-center gap-2 text-sm text-emerald-600 dark:text-emerald-400">
                <Check size={16} /> {msg}
              </div>
            ) : state === "error" ? (
              <div className="flex items-center justify-center gap-2 text-sm text-red-600 dark:text-red-400">
                <AlertCircle size={16} /> {msg}
              </div>
            ) : (
              <button
                onClick={requestCoverage}
                disabled={state === "loading"}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-60 text-white text-sm font-semibold transition-colors"
              >
                {state === "loading" && <Loader2 size={15} className="animate-spin" />}
                Request coverage for {symbol}
              </button>
            )}
            {state !== "done" && state !== "error" && (
              <p className="mt-2 text-xs text-zinc-400 dark:text-zinc-600">
                We&apos;ll verify it and add it to our universe if it&apos;s a real US listing.
              </p>
            )}
          </div>
        )}

        <div className="mt-8 pt-6 border-t border-zinc-200 dark:border-zinc-800 flex items-center justify-center gap-3">
          <Link
            href="/screener"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors"
          >
            <Telescope size={14} /> Browse Screener
          </Link>
          <Link
            href="/"
            className="inline-flex items-center px-3 py-1.5 rounded-lg text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
          >
            Back to Dashboard
          </Link>
        </div>
      </Card>
    </div>
  );
}
