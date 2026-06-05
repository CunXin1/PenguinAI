"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { auth } from "@/lib/api";
import type { User } from "@/lib/types";

const TOKEN_KEY = "access_token";

/** Current-user + auth state, shared by the Navbar and Profile page. */
export function useAuth() {
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const [token, setToken] = useState<string | null>(null);

  // Re-read the token on mount and on every route change (login redirects here).
  useEffect(() => {
    setToken(typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null);
  }, [pathname]);

  const { data: user, isLoading, isError } = useQuery<User>({
    queryKey: ["me"],
    queryFn: () => auth.me(),
    enabled: !!token,
    staleTime: 5 * 60_000,
    retry: false,
  });

  // Token present but rejected (expired / invalid) → drop it so the UI shows logged-out.
  useEffect(() => {
    if (isError && token) {
      localStorage.removeItem(TOKEN_KEY);
      setToken(null);
    }
  }, [isError, token]);

  const logout = () => {
    if (typeof window !== "undefined") localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    qc.removeQueries({ queryKey: ["me"] });
    qc.removeQueries({ queryKey: ["watchlist"] });
    router.push("/");
  };

  const isLoggedIn = !!token && !isError;
  return {
    user: isLoggedIn ? user : undefined,
    isLoggedIn,
    isLoading: isLoading && !!token,
    logout,
  };
}

/** First letter for an avatar badge. */
export function userInitial(user?: User): string {
  return (user?.display_name || user?.email || "U").charAt(0).toUpperCase();
}
