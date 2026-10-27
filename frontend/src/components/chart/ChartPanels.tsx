"use client";

import { LineChart } from "./LineChart";
import type { PricePoint } from "@/lib/priceHistory";

interface MainChartProps {
  ticker: string | null;
  points: PricePoint[];
}

/** Selected-ticker price chart, built from the stream since page load. */
export function MainChart({ ticker, points }: MainChartProps) {
  return (
    <section data-testid="main-chart" data-ticker={ticker ?? undefined} className="flex min-h-0 flex-col bg-terminal-panel">
      <header className="border-b border-terminal-border px-3 py-2 text-xs uppercase tracking-wide text-terminal-muted">
        {ticker ?? "Select a ticker"}
      </header>
      <div className="min-h-64 flex-1">
        <LineChart points={points} />
      </div>
    </section>
  );
}

/** Total portfolio value over time, from the backend snapshots. */
export function PnlChart({ points }: { points: PricePoint[] }) {
  return (
    <section data-testid="pnl-chart" data-point-count={points.length} className="flex min-h-0 flex-col bg-terminal-panel">
      <header className="border-b border-terminal-border px-3 py-2 text-xs uppercase tracking-wide text-terminal-muted">
        Portfolio value
      </header>
      <div className="min-h-56 flex-1">
        <LineChart points={points} />
      </div>
    </section>
  );
}
