// Shared Fear & Greed scale helpers. Score domain is 0–100:
//   0–25 extreme fear · 25–45 fear · 45–55 neutral · 55–75 greed · 75–100 extreme greed

export interface Zone {
  lo: number;
  hi: number;
  label: string;
  hex: string;
}

// Fear = red, Greed = emerald (matches the app's LONG/SHORT palette spirit:
// extreme readings are the actionable ends).
export const ZONES: Zone[] = [
  { lo: 0, hi: 25, label: "Extreme Fear", hex: "#ef4444" }, // red-500
  { lo: 25, hi: 45, label: "Fear", hex: "#f97316" }, // orange-500
  { lo: 45, hi: 55, label: "Neutral", hex: "#eab308" }, // yellow-500
  { lo: 55, hi: 75, label: "Greed", hex: "#84cc16" }, // lime-500
  { lo: 75, hi: 100, label: "Extreme Greed", hex: "#10b981" }, // emerald-500
];

export function zoneFor(score: number): Zone {
  return ZONES.find((z) => score >= z.lo && score <= z.hi) ?? ZONES[2];
}

export function fgColor(score: number): string {
  return zoneFor(score).hex;
}

export function fgLabel(score: number): string {
  return zoneFor(score).label;
}

/** Tailwind text-color class for a score (used for inline labels). */
export function fgTextClass(score: number): string {
  if (score < 25) return "text-red-500";
  if (score < 45) return "text-orange-500";
  if (score <= 55) return "text-yellow-500";
  if (score <= 75) return "text-lime-500";
  return "text-emerald-500";
}
