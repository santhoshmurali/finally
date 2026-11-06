"use client";

import { useEffect, useRef } from "react";
import {
  ColorType,
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { TickPoint } from "@/lib/ticks";

/** Owns one Lightweight Charts line chart; returns the ref to put on its container. */
export function useLineChart(points: TickPoint[], color: string) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const created = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#8b949e" },
      grid: { vertLines: { color: "#21262d" }, horzLines: { color: "#21262d" } },
      timeScale: { timeVisible: true, secondsVisible: true, borderColor: "#30363d" },
      rightPriceScale: { borderColor: "#30363d" },
    });
    chart.current = created;
    series.current = created.addSeries(LineSeries, { color, lineWidth: 2 });
    return () => {
      created.remove();
      chart.current = null;
      series.current = null;
    };
  }, [color]);

  useEffect(() => {
    series.current?.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    chart.current?.timeScale().fitContent();
  }, [points]);

  return container;
}
