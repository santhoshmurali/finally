import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, makeUpdate, makeWatchlistItem } from "@/test/factories";
import { Watchlist } from "./Watchlist";

const items = [makeWatchlistItem("TCS"), makeWatchlistItem("INFY")];

function renderWatchlist(overrides: Partial<Parameters<typeof Watchlist>[0]> = {}) {
  const props = {
    items,
    prices: { TCS: makeUpdate("TCS", 2529), INFY: makeUpdate("INFY", 1500) },
    history: {},
    selectedTicker: null,
    onSelect: vi.fn(),
    onChange: vi.fn(),
    ...overrides,
  };
  render(<Watchlist {...props} />);
  return props;
}

function rowFor(ticker: string): HTMLElement {
  return document.querySelector(`[data-testid="watchlist-row"][data-ticker="${ticker}"]`) as HTMLElement;
}

describe("Watchlist", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders one row per watchlist ticker with the streamed price", () => {
    renderWatchlist();
    expect(screen.getAllByTestId("watchlist-row")).toHaveLength(2);
    expect(within(rowFor("TCS")).getByTestId("watchlist-price")).toHaveTextContent("2,529.00");
  });

  it("flashes green on an uptick and red on a downtick", () => {
    renderWatchlist({
      prices: { TCS: makeUpdate("TCS", 2530, { timestamp: 2, direction: "up" }), INFY: makeUpdate("INFY", 1500) },
    });
    const price = within(rowFor("TCS")).getByTestId("watchlist-price");
    expect(price).toHaveAttribute("data-direction", "up");
    expect(price).toHaveClass("animate-flash-up");
  });

  it("does not flash on a flat tick", () => {
    renderWatchlist();
    expect(within(rowFor("TCS")).getByTestId("watchlist-price")).not.toHaveClass("animate-flash-up");
    expect(within(rowFor("TCS")).getByTestId("watchlist-price")).not.toHaveClass("animate-flash-down");
  });

  it("selects a ticker when its row is clicked", () => {
    const { onSelect } = renderWatchlist();
    fireEvent.click(within(rowFor("INFY")).getByRole("button", { name: /^INFY/ }));
    expect(onSelect).toHaveBeenCalledWith("INFY");
  });

  it("adds an upper-cased ticker, then refreshes the list", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ticker: "WIPRO", added_at: "t" }, 201));
    const { onChange } = renderWatchlist();

    fireEvent.change(screen.getByTestId("watchlist-add-input"), { target: { value: " wipro " } });
    fireEvent.click(screen.getByTestId("watchlist-add-button"));

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(fetch).toHaveBeenCalledWith(
      "/api/watchlist",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ ticker: "WIPRO" }) }),
    );
  });

  it("shows the server message when the add is rejected", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: "Unsupported ticker: FOO" }, 400));
    const { onChange } = renderWatchlist();

    fireEvent.change(screen.getByTestId("watchlist-add-input"), { target: { value: "foo" } });
    fireEvent.click(screen.getByTestId("watchlist-add-button"));

    expect(await screen.findByTestId("watchlist-error")).toHaveTextContent("Unsupported ticker: FOO");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes a ticker through the API and refreshes the list", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(undefined, 204));
    const { onChange } = renderWatchlist();

    fireEvent.click(within(rowFor("TCS")).getByTestId("watchlist-remove"));

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(fetch).toHaveBeenCalledWith("/api/watchlist/TCS", expect.objectContaining({ method: "DELETE" }));
  });
});
