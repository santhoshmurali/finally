import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";
import { TradeBar } from "./TradeBar";
import { api, ApiError } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      trade: vi.fn(),
      chat: vi.fn(),
    },
  };
});

const trade = vi.mocked(api.trade);
const chat = vi.mocked(api.chat);

describe("TradeBar", () => {
  beforeEach(() => {
    trade.mockResolvedValue({
      ticker: "TCS",
      side: "buy",
      quantity: 2,
      price: 2529.36,
      executed_at: "2026-10-27T10:00:00Z",
      cash_balance: 994_000,
    });
  });

  it("buys the typed quantity of the typed ticker and reports the fill", async () => {
    const onTraded = vi.fn();
    render(<TradeBar ticker="TCS" onTraded={onTraded} />);

    fireEvent.change(screen.getByLabelText("Trade quantity"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Buy" }));

    await waitFor(() => expect(trade).toHaveBeenCalledWith("TCS", 2, "buy"));
    expect(await screen.findByRole("status")).toHaveTextContent("Bought 2 TCS at 2,529.36");
    expect(onTraded).toHaveBeenCalledTimes(1);
  });

  it("sells through the sell button", async () => {
    render(<TradeBar ticker="INFY" onTraded={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Sell" }));

    await waitFor(() => expect(trade).toHaveBeenCalledWith("INFY", 1, "sell"));
  });

  it("shows the backend rejection reason", async () => {
    trade.mockRejectedValueOnce(new ApiError("insufficient cash: buying 1 TCS costs 2,529.36", 400));
    const onTraded = vi.fn();
    render(<TradeBar ticker="TCS" onTraded={onTraded} />);

    fireEvent.click(screen.getByRole("button", { name: "Buy" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("insufficient cash");
    expect(onTraded).not.toHaveBeenCalled();
  });
});

describe("ChatPanel", () => {
  it("shows a loading indicator, then the reply with trade confirmations", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof api.chat>>) => void;
    chat.mockReturnValueOnce(new Promise((done) => (resolve = done)));
    const onActionsApplied = vi.fn();
    render(<ChatPanel onActionsApplied={onActionsApplied} />);

    fireEvent.change(screen.getByLabelText("Chat message"), { target: { value: "buy one TCS" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("FinAlly is thinking...")).toBeInTheDocument();
    resolve({
      message: "Done.",
      trades: [{ ticker: "TCS", side: "buy", quantity: 1, price: 2529.36 }],
      watchlist_changes: null,
    });

    expect(await screen.findByText("Done.")).toBeInTheDocument();
    expect(screen.getByText("Bought 1 TCS at 2,529.36")).toBeInTheDocument();
    expect(screen.queryByText("FinAlly is thinking...")).not.toBeInTheDocument();
    expect(onActionsApplied).toHaveBeenCalledTimes(1);
  });

  it("does not refresh portfolio data for a plain reply", async () => {
    chat.mockResolvedValueOnce({ message: "Looks steady.", trades: null, watchlist_changes: null });
    const onActionsApplied = vi.fn();
    render(<ChatPanel onActionsApplied={onActionsApplied} />);

    fireEvent.change(screen.getByLabelText("Chat message"), { target: { value: "how am I doing" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Looks steady.")).toBeInTheDocument();
    expect(onActionsApplied).not.toHaveBeenCalled();
  });

  it("shows watchlist confirmations inline", async () => {
    chat.mockResolvedValueOnce({
      message: "Added it.",
      trades: null,
      watchlist_changes: [{ ticker: "WIPRO", action: "add" }],
    });
    render(<ChatPanel onActionsApplied={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Chat message"), { target: { value: "track wipro" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Added WIPRO to watchlist")).toBeInTheDocument();
  });
});
