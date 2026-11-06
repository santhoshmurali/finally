import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PortfolioHeatmap, tileFill } from "./PortfolioHeatmap";
import { PositionsTable } from "./PositionsTable";
import type { LivePortfolio } from "@/lib/ticks";

const portfolio: LivePortfolio = {
  cash_balance: 500_000,
  total_value: 520_000,
  unrealized_pnl: 20_000,
  positions: [
    {
      ticker: "TCS",
      quantity: 100,
      avg_cost: 2000,
      current_price: 2200,
      market_value: 220_000,
      unrealized_pnl: 20_000,
      unrealized_pnl_percent: 10,
      day_change_percent: 1.5,
      live_price: 2200,
      live_market_value: 220_000,
      live_unrealized_pnl: 20_000,
      live_unrealized_pnl_percent: 10,
    },
    {
      ticker: "INFY",
      quantity: 10,
      avg_cost: 1500,
      current_price: 1400,
      market_value: 14_000,
      unrealized_pnl: -1000,
      unrealized_pnl_percent: -6.67,
      day_change_percent: -0.8,
      live_price: 1400,
      live_market_value: 14_000,
      live_unrealized_pnl: -1000,
      live_unrealized_pnl_percent: -6.67,
    },
  ],
};

describe("PortfolioHeatmap", () => {
  it("draws cash and one tile per position", () => {
    render(<PortfolioHeatmap portfolio={portfolio} />);

    const heatmap = screen.getByTestId("heatmap");
    expect(within(heatmap).getByTestId("tile-CASH")).toHaveAttribute("data-pnl", "cash");
    expect(within(heatmap).getByTestId("tile-TCS")).toHaveAttribute("data-pnl", "10");
    expect(within(heatmap).getByTestId("tile-INFY")).toHaveAttribute("data-pnl", "-6.67");
  });

  it("colours gains green, losses red and cash grey", () => {
    expect(tileFill(null)).toBe("#30363d");
    expect(tileFill(4)).toMatch(/^rgba\(63, 185, 80/);
    expect(tileFill(-4)).toMatch(/^rgba\(248, 81, 73/);
  });
});

describe("PositionsTable", () => {
  it("shows live valuation and P&L for each position", () => {
    render(<PositionsTable portfolio={portfolio} />);

    const tcs = screen.getByTestId("position-TCS");
    expect(within(tcs).getByText("100")).toBeInTheDocument();
    expect(within(tcs).getByText("2,200.00")).toBeInTheDocument();
    expect(within(tcs).getByText(/\+10\.00%/)).toBeInTheDocument();
  });

  it("explains when there are no positions", () => {
    render(<PositionsTable portfolio={{ ...portfolio, positions: [] }} />);

    expect(screen.getByText(/No open positions/)).toBeInTheDocument();
  });
});
