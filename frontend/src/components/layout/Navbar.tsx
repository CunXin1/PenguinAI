"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Telescope,
  CalendarDays,
  Star,
  Newspaper,
  User,
  Search,
  Menu,
  X,
  LayoutGrid,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useAuth, userInitial } from "@/hooks/useAuth";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/heatmap", label: "Market Map", icon: LayoutGrid },
  { href: "/screener", label: "Screener", icon: Telescope },
  { href: "/earnings", label: "Earnings", icon: CalendarDays },
  { href: "/watchlist", label: "Watchlist", icon: Star },
  { href: "/news", label: "News", icon: Newspaper },
  { href: "/profile", label: "Profile", icon: User },
];

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isLoggedIn, logout } = useAuth();
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  // Close menus whenever the route changes.
  useEffect(() => {
    setMenuOpen(false);
    setUserMenuOpen(false);
  }, [pathname]);

  const submitSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const t = query.trim().toUpperCase();
    if (t) {
      router.push(`/signals/${t}`);
      setMenuOpen(false);
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

        {/* Desktop / tablet nav: icon-only from md, labels added at lg */}
        <nav className="hidden md:flex items-center gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = isActive(href);
            return (
              <Link
                key={href}
                href={href}
                title={label}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 lg:px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                  active
                    ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                )}
              >
                <Icon size={15} className="shrink-0" />
                <span className="hidden lg:inline">{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="flex-1" />

        {/* Inline search: shown from md, width grows with the viewport */}
        <form
          onSubmit={submitSearch}
          className="hidden md:flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-1.5 w-36 lg:w-56 focus-within:border-sky-500/60 transition-colors"
        >
          <Search size={14} className="text-zinc-500 shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search ticker..."
            className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-full"
          />
        </form>

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
                      {user?.display_name || user?.email?.split("@")[0] || "Account"}
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
            className="hidden sm:inline-flex px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-white text-sm font-semibold transition-colors shrink-0"
          >
            Sign in
          </Link>
        )}

        {/* Hamburger: mobile only */}
        <button
          type="button"
          onClick={() => setMenuOpen((o) => !o)}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          className="md:hidden w-8 h-8 grid place-items-center rounded-lg text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors shrink-0"
        >
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
      </div>

      {/* Mobile dropdown panel */}
      {menuOpen && (
        <div className="md:hidden border-t border-zinc-200 dark:border-zinc-800 bg-white/95 dark:bg-zinc-950/95 backdrop-blur">
          <div className="max-w-7xl mx-auto px-4 py-3 flex flex-col gap-1">
            <form
              onSubmit={submitSearch}
              className="flex items-center gap-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-3 py-2 mb-2 focus-within:border-sky-500/60 transition-colors"
            >
              <Search size={15} className="text-zinc-500 shrink-0" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search ticker..."
                className="bg-transparent outline-none text-sm text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 w-full"
              />
            </form>

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
