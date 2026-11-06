/** A small inline price line drawn from the values streamed since page load. */

interface SparklineProps {
  values: number[];
  positive: boolean;
}

export function Sparkline({ values, positive }: SparklineProps) {
  const width = 96;
  const height = 28;
  if (values.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" />;
  }
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - low) / span) * (height - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        strokeWidth={1.5}
        className={positive ? "stroke-gain" : "stroke-loss"}
      />
    </svg>
  );
}
