"use client";

import { useLineChart } from "@/components/useLineChart";
import type { TickPoint } from "@/lib/ticks";

interface MainChartProps {
  ticker: string;
  points: TickPoint[];
}

/** Price of the selected ticker since page load, one point per streamed tick. */
export function MainChart({ ticker, points }: MainChartProps) {
  const container = useLineChart(points, "#209dd7");
  return (
    <section aria-label="Price chart" className="flex min-h-0 flex-col">
      <div className="flex items-baseline justify-between px-3 py-2">
        <h2 className="panel-title border-0 p-0">{ticker}</h2>
        <span className="text-xs text-muted">Live price since page load</span>
      </div>
      <div ref={container} data-testid="main-chart" className="min-h-[220px] flex-1" />
    </section>
  );
}
