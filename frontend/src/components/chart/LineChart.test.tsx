import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LineChart } from "./LineChart";

const series = { setData: vi.fn() };
const timeScale = { fitContent: vi.fn() };
const chart = { addSeries: vi.fn(() => series), timeScale: vi.fn(() => timeScale), remove: vi.fn() };

vi.mock("lightweight-charts", () => ({
  LineSeries: "LineSeries",
  createChart: vi.fn(() => chart),
}));

describe("LineChart", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates one chart and one line series", () => {
    render(<LineChart points={[]} />);
    expect(chart.addSeries).toHaveBeenCalledTimes(1);
  });

  it("feeds the points to the series and fits the time scale", () => {
    const { rerender } = render(<LineChart points={[]} />);
    rerender(<LineChart points={[{ time: 100, value: 2529 }]} />);

    expect(series.setData).toHaveBeenLastCalledWith([{ time: 100, value: 2529 }]);
    expect(timeScale.fitContent).toHaveBeenCalled();
  });

  it("removes the chart on unmount", () => {
    const { unmount } = render(<LineChart points={[]} />);
    unmount();
    expect(chart.remove).toHaveBeenCalledTimes(1);
  });
});
