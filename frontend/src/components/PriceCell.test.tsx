import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FLASH_MS, PriceCell } from "./PriceCell";

describe("PriceCell", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("flashes green on an uptick and fades after the flash window", () => {
    const { rerender } = render(<PriceCell value={100} />);
    expect(screen.getByTestId("price")).toHaveAttribute("data-flash", "none");

    rerender(<PriceCell value={101.5} />);
    expect(screen.getByTestId("price")).toHaveAttribute("data-flash", "up");
    expect(screen.getByTestId("price")).toHaveClass("flash-up");

    act(() => vi.advanceTimersByTime(FLASH_MS));
    expect(screen.getByTestId("price")).toHaveAttribute("data-flash", "none");
  });

  it("flashes red on a downtick", () => {
    const { rerender } = render(<PriceCell value={100} />);

    rerender(<PriceCell value={99} />);

    expect(screen.getByTestId("price")).toHaveClass("flash-down");
  });

  it("does not flash when the price is unchanged", () => {
    const { rerender } = render(<PriceCell value={100} />);

    rerender(<PriceCell value={100} />);

    expect(screen.getByTestId("price")).toHaveAttribute("data-flash", "none");
  });

  it("shows a dash when there is no price yet", () => {
    render(<PriceCell value={null} />);

    expect(screen.getByTestId("price")).toHaveTextContent("--");
  });
});
