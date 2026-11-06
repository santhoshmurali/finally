"use client";

import { useLineChart } from "@/components/useLineChart";
import type { SnapshotPoint } from "@/lib/types";
import type { TickPoint } from "@/lib/ticks";
import { useMemo } from "react";

/** Snapshots become one point per second, keeping the last value when two share a second. */
export function snapshotsToPoints(snapshots: SnapshotPoint[]): TickPoint[] {
  const points: TickPoint[] = [];
  for (const snapshot of snapshots) {
    const time = Math.floor(Date.parse(snapshot.recorded_at) / 1000);
    const last = points[points.length - 1];
    if (last && last.time === time) {
      last.value = snapshot.total_value;
    } else {
      points.push({ time, value: snapshot.total_value });
    }
  }
  return points;
}

interface PnlChartProps {
  snapshots: SnapshotPoint[];
}

/** Total portfolio value over time, from the recorded snapshots. */
export function PnlChart({ snapshots }: PnlChartProps) {
  const points = useMemo(() => snapshotsToPoints(snapshots), [snapshots]);
  const container = useLineChart(points, "#ecad0a");
  return (
    <section aria-label="Portfolio value chart" className="flex min-h-0 flex-col">
      <h2 className="panel-title">Portfolio value</h2>
      <div ref={container} data-testid="pnl-chart" className="min-h-[160px] flex-1" />
    </section>
  );
}
