export interface CelebrityMeta {
  slug: string;
  name: string;
  title: string;
  avatar: string;
  image?: string;
}

export const CELEBRITIES: Record<string, CelebrityMeta> = {
  buffett: { slug: "buffett", name: "Warren Buffett", title: "Berkshire Hathaway", avatar: "WB", image: "/avatars/buffett.webp?v=2" },
  soros: { slug: "soros", name: "George Soros", title: "Soros Fund Management", avatar: "GS", image: "/avatars/soros.webp?v=2" },
  dalio: { slug: "dalio", name: "Ray Dalio", title: "Bridgewater Associates", avatar: "RD", image: "/avatars/dalio.webp?v=2" },
  ackman: { slug: "ackman", name: "Bill Ackman", title: "Pershing Square", avatar: "BA", image: "/avatars/ackman.webp?v=2" },
  cathie_wood: { slug: "cathie_wood", name: "Cathie Wood", title: "ARK Invest", avatar: "CW", image: "/avatars/cathie_wood.webp?v=2" },
  pelosi: { slug: "pelosi", name: "Nancy Pelosi", title: "U.S. House Speaker", avatar: "NP", image: "/avatars/pelosi.webp?v=2" },
  tuberville: { slug: "tuberville", name: "Tommy Tuberville", title: "U.S. Senate", avatar: "TT", image: "/avatars/tuberville.webp?v=2" },
  mtg: { slug: "mtg", name: "Marjorie Taylor Greene", title: "U.S. House", avatar: "MG", image: "/avatars/mtg.webp?v=2" },
  crenshaw: { slug: "crenshaw", name: "Dan Crenshaw", title: "U.S. House", avatar: "DC", image: "/avatars/crenshaw.webp?v=2" },
  trump: { slug: "trump", name: "Donald Trump", title: "U.S. President", avatar: "DT", image: "/avatars/trump.webp?v=2" },
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
