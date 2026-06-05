import Link from "next/link";
import { Newspaper, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { MOCK_NEWS } from "@/lib/mock";

const DOT: Record<string, string> = {
  positive: "bg-emerald-400",
  negative: "bg-red-400",
  neutral: "bg-zinc-500",
};

export function NewsPreview() {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-300 flex items-center gap-2">
          <Newspaper size={15} className="text-sky-400" />
          Latest News
        </h3>
        <Link href="/news" className="text-xs text-zinc-500 hover:text-sky-400 flex items-center gap-1 transition-colors">
          All <ArrowRight size={12} />
        </Link>
      </div>
      <div className="space-y-3">
        {MOCK_NEWS.slice(0, 4).map((n) => (
          <Link key={n.id} href={`/news/${n.id}`} className="block group">
            <div className="flex gap-2.5">
              <span className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${DOT[n.sentiment]}`} />
              <div className="min-w-0">
                <p className="text-sm text-zinc-300 leading-snug group-hover:text-white transition-colors line-clamp-2">
                  {n.headline}
                </p>
                <p className="text-[11px] text-zinc-600 mt-0.5">
                  {n.source} · {n.time}
                  {n.tickers && n.tickers.length > 0 ? ` · ${n.tickers.join(", ")}` : ""}
                </p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </Card>
  );
}
