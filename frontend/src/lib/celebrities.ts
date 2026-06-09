export interface CelebrityMeta {
  slug: string;
  name: string;
  title: string;
  avatar: string;
}

export const CELEBRITIES: Record<string, CelebrityMeta> = {
  buffett: { slug: "buffett", name: "Warren Buffett", title: "Berkshire Hathaway", avatar: "WB" },
  soros: { slug: "soros", name: "George Soros", title: "Soros Fund Management", avatar: "GS" },
  dalio: { slug: "dalio", name: "Ray Dalio", title: "Bridgewater Associates", avatar: "RD" },
  ackman: { slug: "ackman", name: "Bill Ackman", title: "Pershing Square", avatar: "BA" },
  pelosi: { slug: "pelosi", name: "Nancy Pelosi", title: "U.S. House of Representatives", avatar: "NP" },
  cathie_wood: { slug: "cathie_wood", name: "Cathie Wood", title: "ARK Invest", avatar: "CW" },
  tuberville: { slug: "tuberville", name: "Tommy Tuberville", title: "U.S. Senate", avatar: "TT" },
  goldman: { slug: "goldman", name: "Daniel Goldman", title: "U.S. House of Representatives", avatar: "DG" },
  mark_green: { slug: "mark_green", name: "Mark Green", title: "U.S. House of Representatives", avatar: "MG" },
  gottheimer: { slug: "gottheimer", name: "Josh Gottheimer", title: "U.S. House of Representatives", avatar: "JG" },
  khanna: { slug: "khanna", name: "Ro Khanna", title: "U.S. House of Representatives", avatar: "RK" },
  mccaul: { slug: "mccaul", name: "Michael McCaul", title: "U.S. House of Representatives", avatar: "MM" },
  crenshaw: { slug: "crenshaw", name: "Dan Crenshaw", title: "U.S. House of Representatives", avatar: "DC" },
  mtg: { slug: "mtg", name: "Marjorie Taylor Greene", title: "U.S. House of Representatives", avatar: "MG" },
};

const AVATAR_COLORS = [
  "from-sky-400 to-sky-600",
  "from-emerald-400 to-emerald-600",
  "from-amber-400 to-amber-600",
  "from-violet-400 to-violet-600",
  "from-rose-400 to-rose-600",
  "from-cyan-400 to-cyan-600",
  "from-orange-400 to-orange-600",
  "from-fuchsia-400 to-fuchsia-600",
];

export function getCelebrityMeta(slug: string): CelebrityMeta {
  return CELEBRITIES[slug] ?? { slug, name: slug, title: "Investor", avatar: slug.slice(0, 2).toUpperCase() };
}

export function getCelebrityColor(slug: string): string {
  const keys = Object.keys(CELEBRITIES);
  const idx = keys.indexOf(slug);
  return AVATAR_COLORS[(idx >= 0 ? idx : slug.length) % AVATAR_COLORS.length];
}
