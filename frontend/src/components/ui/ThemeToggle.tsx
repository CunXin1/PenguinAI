"use client";

import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";

/**
 * Light/dark theme switch. Toggles the `dark` class on <html> and persists the
 * choice to localStorage (read back before paint by the inline script in the
 * root layout, so there is no flash on reload).
 */
export function ThemeToggle() {
  const [dark, setDark] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
    setMounted(true);
  }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      /* ignore storage errors (private mode, etc.) */
    }
  };

  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
      className="w-8 h-8 grid place-items-center rounded-lg text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors shrink-0"
    >
      {/* Render a stable icon until mounted to avoid hydration mismatch */}
      {mounted && !dark ? <Moon size={16} /> : <Sun size={16} />}
    </button>
  );
}
