import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** Base surface — dark card consistent with the zinc-950 theme. */
export function Card({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/60",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
