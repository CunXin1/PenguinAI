/** Lightweight dependency-free SVG sparkline. Optional `fill` draws a soft area. */
export function Sparkline({
  data,
  color = "#a1a1aa",
  width = 64,
  height = 20,
  className,
  fill = false,
}: {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
  className?: string;
  fill?: boolean;
}) {
  if (!data || data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  // Inset the line a touch from the top/bottom edges so peaks aren't clipped.
  const pad = 1.5;
  const y = (v: number) => pad + (height - 2 * pad) * (1 - (v - min) / range);

  const coords = data.map((v, i) => [i * step, y(v)] as const);
  const points = coords.map(([x, py]) => `${x.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const area = fill
    ? `0,${height} ` + points + ` ${((data.length - 1) * step).toFixed(1)},${height}`
    : null;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden
    >
      {area && <polygon points={area} fill={color} fillOpacity={0.12} stroke="none" />}
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
