import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Header } from "./Header";

describe("Header", () => {
  it("shows the portfolio and cash in rupees", () => {
    render(<Header totalValue={1_000_000} cashBalance={500_000} status="open" />);
    expect(screen.getByTestId("header-total-value")).toHaveTextContent("₹10,00,000.00");
    expect(screen.getByTestId("header-cash")).toHaveTextContent("₹5,00,000.00");
  });

  it("maps the connection status to a dot colour and label", () => {
    const { rerender } = render(<Header totalValue={null} cashBalance={null} status="open" />);
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-state", "open");
    expect(screen.getByTestId("connection-status")).toHaveTextContent("Live");

    rerender(<Header totalValue={null} cashBalance={null} status="reconnecting" />);
    expect(screen.getByTestId("connection-status")).toHaveTextContent("Reconnecting");
    expect(screen.getByTestId("connection-status").querySelector("span")).toHaveClass("bg-accent");

    rerender(<Header totalValue={null} cashBalance={null} status="closed" />);
    expect(screen.getByTestId("connection-status").querySelector("span")).toHaveClass("bg-loss");
  });

  it("shows placeholders until the account has loaded", () => {
    render(<Header totalValue={null} cashBalance={null} status="reconnecting" />);
    expect(screen.getByTestId("header-total-value")).toHaveTextContent("--");
  });
});
