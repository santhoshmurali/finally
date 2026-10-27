import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse } from "@/test/factories";
import { useAccountData } from "./useAccountData";

const portfolio = { cash_balance: 1_000_000, total_value: 1_000_000, unrealized_pnl: 0, positions: [] };

describe("useAccountData", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the account and reports no error", async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      if (String(input) === "/api/portfolio") return Promise.resolve(jsonResponse(portfolio));
      return Promise.resolve(jsonResponse([]));
    });

    const { result } = renderHook(() => useAccountData());

    await waitFor(() => expect(result.current.portfolio).toEqual(portfolio));
    expect(result.current.error).toBeNull();
  });

  it("reports the failure when the backend cannot be reached, then clears it on the next good load", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useAccountData());
    await waitFor(() => expect(result.current.error).toBe("Failed to fetch"));

    vi.mocked(fetch).mockImplementation((input) => {
      if (String(input) === "/api/portfolio") return Promise.resolve(jsonResponse(portfolio));
      return Promise.resolve(jsonResponse([]));
    });
    await act(() => result.current.refresh());

    expect(result.current.error).toBeNull();
    expect(result.current.portfolio).toEqual(portfolio);
  });
});
