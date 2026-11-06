import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WatchlistPanel } from "./WatchlistPanel";
import type { PriceUpdate, WatchEntry } from "@/lib/types";

const entries: WatchEntry[] = [
  { ticker: "TCS", price: 2500, previous_price: 2499, day_change_percent: 1.2, direction: "up" },
  { ticker: "INFY", price: 1200, previous_price: 1200, day_change_percent: -0.5, direction: "flat" },
];

function quote(ticker: string, price: number): PriceUpdate {
  return {
    ticker,
    price,
    previous_price: price,
    previous_close: price,
    timestamp: 1000,
    change: 0,
    direction: "flat",
    day_change: 0,
    day_change_percent: 0,
  };
}

function renderPanel(overrides: Partial<Parameters<typeof WatchlistPanel>[0]> = {}) {
  const props = {
    entries,
    prices: {},
    history: {},
    selected: "TCS",
    error: null,
    onSelect: vi.fn(),
    onAdd: vi.fn(async () => true),
    onRemove: vi.fn(async () => undefined),
    ...overrides,
  };
  render(<WatchlistPanel {...props} />);
  return props;
}

describe("WatchlistPanel", () => {
  it("lists tickers with the streamed price when one is available", () => {
    renderPanel({ prices: { TCS: quote("TCS", 2650) } });

    expect(screen.getByTestId("watch-TCS")).toHaveTextContent("2,650.00");
    expect(screen.getByTestId("watch-INFY")).toHaveTextContent("1,200.00");
  });

  it("selects a ticker when its name is clicked", () => {
    const props = renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "INFY" }));

    expect(props.onSelect).toHaveBeenCalledWith("INFY");
  });

  it("adds the typed ticker and clears the field on success", async () => {
    const props = renderPanel();
    const input = screen.getByLabelText("Ticker to add");

    fireEvent.change(input, { target: { value: " wipro " } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(props.onAdd).toHaveBeenCalledWith("wipro"));
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("keeps the typed ticker when the add is rejected", async () => {
    const props = renderPanel({ onAdd: vi.fn(async () => false) });
    const input = screen.getByLabelText("Ticker to add");

    fireEvent.change(input, { target: { value: "NOPE" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(props.onAdd).toHaveBeenCalled());
    expect(input).toHaveValue("NOPE");
  });

  it("removes a ticker from its row", () => {
    const props = renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "Remove TCS" }));

    expect(props.onRemove).toHaveBeenCalledWith("TCS");
  });

  it("shows the watchlist error", () => {
    renderPanel({ error: "INFY is already on the watchlist" });

    expect(screen.getByRole("alert")).toHaveTextContent("already on the watchlist");
  });
});
