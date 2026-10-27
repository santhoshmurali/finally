import type { PricePoint } from "@/lib/priceHistory";

interface SparklineProps {
  points: PricePoint[];
}

const WIDTH = 80;
const HEIGHT = 24;

/** A tiny inline line chart of recent prices, scaled to its own min and max. */
export function Sparkline({ points }: SparklineProps) {
  const svgProps = {
    viewBox: `0 0 ${WIDTH} ${HEIGHT}`,
    preserveAspectRatio: "none",
    className: "h-6 w-full min-w-0",
    "aria-hidden": true,
  } as const;
  if (points.length < 2) {
    return <svg {...svgProps} />;
  }
  const values = points.map((point) => point.value);
  const low = Math.min(...values);
  const range = Math.max(...values) - low || 1;
  const coordinates = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * WIDTH;
      const y = HEIGHT - ((point.value - low) / range) * HEIGHT;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <svg {...svgProps}>
      <polyline
        points={coordinates}
        fill="none"
        className="stroke-primary"
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
