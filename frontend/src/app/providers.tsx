"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { MarketStatusProvider } from "@/lib/market-status";

/** Global client-side providers (React Query for server-state caching, plus the
 *  app-wide market open/closed state). */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60_000,
            retry: 2,
            retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 15_000),
            // Refetch when the user returns to the tab so every surface (earnings,
            // news, fundamentals, signals — not just the interval-polled live
            // quotes) shows current data on focus. Gated by each query's
            // `staleTime`, so fresh-enough data is not re-fetched.
            refetchOnWindowFocus: true,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={client}>
      <MarketStatusProvider>{children}</MarketStatusProvider>
    </QueryClientProvider>
  );
}
