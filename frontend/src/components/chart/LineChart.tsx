"use client";

import { useEffect, useRef } from "react";
import { createChart, LineSeries, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { formatPrice } from "@/lib/format";
import type { PricePoint } from "@/lib/priceHistory";

/** Chart colours mirror the terminal tokens in globals.css (the canvas cannot read CSS variables). */
const CHART_THEME = {
  background: "#0d1117",
  text: "#8b949e",
  grid: "#21262d",
  line: "#209dd7",
};

interface LineChartProps {
  points: PricePoint[];
}

/** A canvas line chart that fills its parent and redraws whenever `points` changes. */
export function LineChart({ points }: LineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, {
      autoSize: true,
      layout: { background: { color: CHART_THEME.background }, textColor: CHART_THEME.text },
      grid: { vertLines: { color: CHART_THEME.grid }, horzLines: { color: CHART_THEME.grid } },
      timeScale: { timeVisible: true, secondsVisible: true, borderColor: CHART_THEME.grid },
      rightPriceScale: { borderColor: CHART_THEME.grid },
      localization: { priceFormatter: formatPrice },
    });
    chartRef.current = chart;
    seriesRef.current = chart.addSeries(LineSeries, { color: CHART_THEME.line, lineWidth: 2 });
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    seriesRef.current?.setData(points.map((point) => ({ time: point.time as UTCTimestamp, value: point.value })));
    chartRef.current?.timeScale().fitContent();
  }, [points]);

  return <div ref={containerRef} className="h-full w-full" />;
}
