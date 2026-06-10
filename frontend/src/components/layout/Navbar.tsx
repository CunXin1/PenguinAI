"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  LayoutDashboard,
  Telescope,
  CalendarDays,
  Crown,
  Landmark,
  Gauge,
  Star,
  Newspaper,
  User,
  Search,
  Menu,
  X,
  LayoutGrid,
  LogIn,
  LogOut,
  Loader2,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { MarketStatusBadge } from "@/components/ui/MarketStatusBadge";
import { useAuth, userInitial } from "@/hooks/useAuth";
import { tickers } from "@/lib/api";
import type { TickerSearchResult } from "@/lib/types";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/heatmap", label: "Market Map", icon: LayoutGrid },
  { href: "/screener", label: "Screener", icon: Telescope },
  { href: "/earnings", label: "Earnings", icon: CalendarDays },
  { href: "/celebrity-holdings", label: "Celebrity", icon: Crown },
  { href: "/fomc", label: "FOMC", icon: Landmark },
  { href: "/fear-greed", label: "Fear & Greed", icon: Gauge },
  { href: "/watchlist", label: "Watchlist", icon: Star },
  { href: "/news", label: "News", icon: Newspaper },
];

/* ── Autocomplete dropdown (shared by desktop + mobile) ──────────────────── */
function SearchDropdown({
  results,
  loading,
  open,
  activeIndex,
  onSelect,
}: {
  results: TickerSearchResult[];
  loading: boolean;
  open: boolean;
  activeIndex: number;
  onSelect: (ticker: string) => void;
}) {
  if (!open) return null;

  return (
    <div className="absolute left-0 right-0 top-full mt-1 z-50 max-h-80 overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-lg">
      {loading ? (
        <div className="flex items-center gap-2 px-3 py-3 text-xs text-zinc-500 dark:text-zinc-400">
          <Loader2 size={14} className="animate-spin shrink-0" />
          Searching...
        </div>
      ) : results.length === 0 ? (
        <div className="px-3 py-3 text-xs text-zinc-500 dark:text-zinc-400">
          No matches
        </div>
      ) : (
        results.map((r, i) => (
          <button
            key={r.ticker}
            type="button"
            onMouseDown={(e) => {
              // Use mousedown instead of click to fire before input blur
              e.preventDefault();
              onSelect(r.ticker);
            }}
            className={cn(
              "w-full flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors text-left",
              i === activeIndex
                ? "bg-zinc-100 dark:bg-zinc-800"
                : "hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
            )}
          >
            <span className="font-semibold text-sm text-zinc-900 dark:text-white shrink-0">
              {r.ticker}
            </span>
            <span className="text-xs text-zinc-500 dark:text-zinc-400 truncate min-w-0">
              {r.name}
            </span>
            {r.sector && (
              <span className="text-xs text-zinc-400 dark:text-zinc-500 ml-auto shrink-0 whitespace-nowrap">
                {r.sector}
              </span>
            )}
          </button>
        ))
      )}
    </div>
  );
}

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isLoggedIn, logout } = useAuth();
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  // Autocomplete state
  const [results, setResults] = useState<TickerSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const desktopDropdownRef = useRef<HTMLDivElement>(null);
  const mobileDropdownRef = useRef<HTMLDivElement>(null);

  // Close menus whenever the route changes.
  useEffect(() => {
    setMenuOpen(false);
    setUserMenuOpen(false);
    setDropdownOpen(false);
  }, [pathname]);

  // Click-outside detection
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (
        desktopDropdownRef.current?.contains(target) ||
        mobileDropdownRef.current?.contains(target)
      ) return;
      setDropdownOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Debounced search
  const performSearch = useCallback((q: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    const trimmed = q.trim();
    if (trimmed.length < 1) {
      setResults([]);
      setDropdownOpen(false);
      setLoading(false);
      return;
    }

    setLoading(true);
    setDropdownOpen(true);

    debounceRef.current = setTimeout(async () => {
      try {
        const data = await tickers.search(trimmed);
        setResults(data.slice(0, 8));
        setActiveIndex(-1);
        setDropdownOpen(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setQuery(v);
    performSearch(v);
  };

  const navigateToTicker = useCallback(
    (ticker: string) => {
      router.push(`/signals/${ticker.toUpperCase()}`);
      setQuery("");
      setResults([]);
      setDropdownOpen(false);
      setMenuOpen(false);
      setActiveIndex(-1);
    },
    [router]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!dropdownOpen || results.length === 0) {
      // Enter with no dropdown: fallback to direct navigation
      if (e.key === "Enter") return; // let form submit handle it
      return;
    }

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((prev) => (prev < results.length - 1 ? prev + 1 : 0));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((prev) => (prev > 0 ? prev - 1 : results.length - 1));
        break;
      case "Enter":
        e.preventDefault();
        if (activeIndex >= 0 && activeIndex < results.length) {
          navigateToTicker(results[activeIndex].ticker);
        } else {
          // No highlighted result — navigate to typed ticker
          const t = query.trim().toUpperCase();
          if (t) navigateToTicker(t);
        }
        break;
      case "Escape":
        e.preventDefault();
        setDropdownOpen(false);
        setActiveIndex(-1);
        break;
    }
  };

  const submitSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const t = query.trim().toUpperCase();
    if (t) {
      navigateToTicker(t);
    }
  };

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-50 border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-950/80 backdrop-blur">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center gap-2 sm:gap-4">
        <Link href="/" className="text-lg font-bold tracking-tight shrink-0">
          <span className="text-zinc-900 dark:text-white">Penguin</span>
          <span className="text-sky-500 dark:text-sky-400">AI</span>
        </Link>

        {/* Global market open/closed badge — single source of truth (useMarketStatus). */}
        <MarketStatusBadge className="hidden sm:inline-flex shrink-0" />

        {/* Nav: icons from sm, labels added at xl */}
        <nav className="hidden sm:flex items-center gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = isActive(href);
            return (
              <Link
                key={href}
                href={href}
                title={label}
                className={cn(
                  "flex items-center gap-1 px-1.5 xl:px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors",
                  active
                    ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                )}
              >
                <Icon size={15} className="shrink-0" />
                <span className="hidden xl:inline whitespace-nowrap">{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="flex-1" />

        {/* Inline search: shown from md, width grows with the viewport */}
        <div ref={desktopDropdownRef} className="relative">
          <form
            onSubmit={submitSearch}
            className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-2 sm:px-3 py-1.5 w-16 sm:w-24 md:w-32 lg:w-40 xl:w-48 focus-within:border-sky-500/60 transition-colors"
          >
            <Search size={14} className="text-zinc-500 shrink-0" />
            <input
              value={query}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              onFocus={() => {
                if (query.trim().length >= 1 && results.length > 0) {
                  setDropdownOpen(true);
                }
              }}
              placeholder="Search ticker..."
              className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-full"
              autoComplete="off"
            />
          </form>
          <SearchDropdown
            results={results}
            loading={loading}
            open={dropdownOpen}
            activeIndex={activeIndex}
            onSelect={navigateToTicker}
          />
        </div>

        <ThemeToggle />

        {isLoggedIn ? (
          <div className="relative shrink-0">
            <button
              type="button"
              onClick={() => setUserMenuOpen((o) => !o)}
              aria-label="Account menu"
              aria-expanded={userMenuOpen}
              className="w-8 h-8 rounded-full bg-gradient-to-br from-sky-400 to-sky-600 grid place-items-center text-sm font-bold text-white"
            >
              {userInitial(user)}
            </button>
            {userMenuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setUserMenuOpen(false)} />
                <div className="absolute right-0 mt-2 w-52 z-50 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-lg py-1">
                  <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800">
                    <p className="text-sm font-medium text-zinc-900 dark:text-white truncate">
                      {user?.username || user?.display_name || user?.email?.split("@")[0] || "Account"}
                    </p>
                    {user?.email && <p className="text-xs text-zinc-500 truncate">{user.email}</p>}
                  </div>
                  <Link
                    href="/profile"
                    onClick={() => setUserMenuOpen(false)}
                    className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                  >
                    <User size={15} /> Profile
                  </Link>
                  {user?.tier === "ADMIN" && (
                    <Link
                      href="/admin"
                      onClick={() => setUserMenuOpen(false)}
                      className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                    >
                      <Settings size={15} /> Admin
                    </Link>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setUserMenuOpen(false);
                      logout();
                    }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-500 dark:text-red-400 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 text-left"
                  >
                    <LogOut size={15} /> Sign out
                  </button>
                </div>
              </>
            )}
          </div>
        ) : (
          <Link
            href="/auth/login"
            className="inline-flex items-center justify-center px-1.5 sm:px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-white text-sm font-semibold transition-colors shrink-0"
          >
            <LogIn size={16} className="sm:hidden" />
            <span className="hidden sm:inline">Sign in</span>
          </Link>
        )}

        {/* Hamburger: mobile only */}
        <button
          type="button"
          onClick={() => setMenuOpen((o) => !o)}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          className="sm:hidden w-8 h-8 grid place-items-center rounded-lg text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors shrink-0"
        >
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
      </div>

      {/* Mobile dropdown panel */}
      {menuOpen && (
        <div className="sm:hidden border-t border-zinc-200 dark:border-zinc-800 bg-white/95 dark:bg-zinc-950/95 backdrop-blur">
          <div className="max-w-7xl mx-auto px-4 py-3 flex flex-col gap-1">
            <div ref={mobileDropdownRef} className="relative mb-2">
              <form
                onSubmit={submitSearch}
                className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 focus-within:border-sky-500/60 transition-colors"
              >
                <Search size={15} className="text-zinc-500 shrink-0" />
                <input
                  value={query}
                  onChange={handleInputChange}
                  onKeyDown={handleKeyDown}
                  onFocus={() => {
                    if (query.trim().length >= 1 && results.length > 0) {
                      setDropdownOpen(true);
                    }
                  }}
                  placeholder="Search ticker..."
                  className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-full"
                  autoComplete="off"
                />
              </form>
              <SearchDropdown
                results={results}
                loading={loading}
                open={dropdownOpen}
                activeIndex={activeIndex}
                onSelect={navigateToTicker}
              />
            </div>

            {NAV.map(({ href, label, icon: Icon }) => {
              const active = isActive(href);
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setMenuOpen(false)}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                    active
                      ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                      : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                  )}
                >
                  <Icon size={17} className="shrink-0" />
                  {label}
                </Link>
              );
            })}

            {isLoggedIn ? (
              <>
                {user?.tier === "ADMIN" && (
                  <Link
                    href="/admin"
                    onClick={() => setMenuOpen(false)}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                      pathname.startsWith("/admin")
                        ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                        : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                    )}
                  >
                    <Settings size={17} className="shrink-0" />
                    Admin
                  </Link>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    logout();
                  }}
                  className="mt-2 flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-800 text-red-500 dark:text-red-400 text-sm font-semibold transition-colors"
                >
                  <LogOut size={16} /> Sign out
                </button>
              </>
            ) : (
              <Link
                href="/auth/login"
                onClick={() => setMenuOpen(false)}
                className="mt-2 px-3 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-white text-sm font-semibold text-center transition-colors"
              >
                Sign in
              </Link>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
