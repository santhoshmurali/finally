import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { LivePosition } from "@/lib/valuation";
import { PositionsTable } from "./PositionsTable";

const tcs: LivePosition = {
  ticker: "TCS",
  quantity: 10,
  avgCost: 2500,
  price: 2529,
  marketValue: 25290,
  unrealizedPnl: 290,
  unrealizedPnlPercent: 11.6,
  dayChangePercent: -0.4,
};

describe("PositionsTable", () => {
  it("renders each position with its formatted figures", () => {
    render(<PositionsTable positions={[tcs]} />);
    const row = screen.getByTestId("position-row");
    expect(row).toHaveAttribute("data-ticker", "TCS");
    expect(within(row).getByText("2,500.00")).toBeInTheDocument();
    expect(within(row).getByText("+₹290.00")).toHaveClass("text-gain");
    expect(within(row).getByText("-0.40%")).toHaveClass("text-loss");
  });

  it("shows an empty state when there are no positions", () => {
    render(<PositionsTable positions={[]} />);
    expect(screen.queryAllByTestId("position-row")).toHaveLength(0);
    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });
});
