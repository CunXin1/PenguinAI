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
            retry: 1,
            refetchOnWindowFocus: false,
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
