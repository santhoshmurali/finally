import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse } from "@/test/factories";
import { TradeBar } from "./TradeBar";

const fillResponse = {
  trade: { id: "t1", ticker: "TCS", side: "buy", quantity: 10, price: 2529, executed_at: "t" },
  portfolio: { cash_balance: 974710, total_value: 1000000, unrealized_pnl: 0, positions: [] },
};

function enterOrder(ticker: string, quantity: string) {
  fireEvent.change(screen.getByTestId("trade-ticker"), { target: { value: ticker } });
  fireEvent.change(screen.getByTestId("trade-quantity"), { target: { value: quantity } });
}

describe("TradeBar", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps both buttons disabled until a ticker and a positive quantity are entered", () => {
    render(<TradeBar onTraded={vi.fn()} />);
    expect(screen.getByTestId("trade-buy")).toBeDisabled();

    enterOrder("tcs", "0");
    expect(screen.getByTestId("trade-buy")).toBeDisabled();

    enterOrder("tcs", "10");
    expect(screen.getByTestId("trade-buy")).toBeEnabled();
    expect(screen.getByTestId("trade-sell")).toBeEnabled();
  });

  it("posts a buy as a market order and reports the fill", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(fillResponse));
    const onTraded = vi.fn();
    render(<TradeBar onTraded={onTraded} />);

    enterOrder("tcs", "10");
    fireEvent.click(screen.getByTestId("trade-buy"));

    expect(await screen.findByTestId("trade-message")).toHaveTextContent("Bought 10 TCS @ ₹2,529.00");
    expect(fetch).toHaveBeenCalledWith(
      "/api/portfolio/trade",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ ticker: "TCS", quantity: 10, side: "buy" }) }),
    );
    await waitFor(() => expect(onTraded).toHaveBeenCalledTimes(1));
  });

  it("shows the server's rejection message and does not refresh", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: "Insufficient cash" }, 400));
    const onTraded = vi.fn();
    render(<TradeBar onTraded={onTraded} />);

    enterOrder("TCS", "1000000");
    fireEvent.click(screen.getByTestId("trade-sell"));

    expect(await screen.findByTestId("trade-message")).toHaveAttribute("data-tone", "error");
    expect(screen.getByTestId("trade-message")).toHaveTextContent("Insufficient cash");
    expect(onTraded).not.toHaveBeenCalled();
  });
});
