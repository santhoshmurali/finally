import type { PriceUpdate, WatchlistItem } from "@/lib/types";

/** A price update in the shape the SSE stream sends. Defaults describe a flat, unchanged tick. */
export function makeUpdate(ticker: string, price: number, overrides: Partial<PriceUpdate> = {}): PriceUpdate {
  return {
    ticker,
    price,
    previous_price: price,
    previous_close: price,
    timestamp: 1_700_000_000,
    change: 0,
    direction: "flat",
    day_change: 0,
    day_change_percent: 0,
    ...overrides,
  };
}

export function makeWatchlistItem(ticker: string, overrides: Partial<WatchlistItem> = {}): WatchlistItem {
  return {
    ticker,
    added_at: "2026-10-27T09:00:00Z",
    price: null,
    previous_close: null,
    day_change_percent: null,
    ...overrides,
  };
}

/** Builds a JSON Response for a stubbed fetch. */
export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
