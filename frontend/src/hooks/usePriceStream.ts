"use client";

import { useEffect, useState } from "react";
import { appendTick, type PriceHistory } from "@/lib/priceHistory";
import type { PriceUpdate } from "@/lib/types";

export const PRICE_STREAM_URL = "/api/stream/prices";

/** `open` is green, `reconnecting` is yellow, `closed` is red. */
export type ConnectionStatus = "open" | "reconnecting" | "closed";

export interface PriceStreamState {
  prices: Record<string, PriceUpdate>;
  history: PriceHistory;
  status: ConnectionStatus;
}

export const INITIAL_PRICE_STREAM: PriceStreamState = {
  prices: {},
  history: {},
  status: "reconnecting",
};

/** Merges one SSE event (all priced tickers) into the stream state. */
export function applyPriceEvent(
  state: PriceStreamState,
  updates: Record<string, PriceUpdate>,
): PriceStreamState {
  const history = { ...state.history };
  for (const update of Object.values(updates)) {
    history[update.ticker] = appendTick(history[update.ticker] ?? [], update);
  }
  return { ...state, prices: { ...state.prices, ...updates }, history, status: "open" };
}

/** Subscribes to the live price stream and keeps prices, sparkline history and status. */
export function usePriceStream(): PriceStreamState {
  const [state, setState] = useState(INITIAL_PRICE_STREAM);

  useEffect(() => {
    const source = new EventSource(PRICE_STREAM_URL);
    source.onopen = () => setState((current) => ({ ...current, status: "open" }));
    source.onmessage = (event: MessageEvent<string>) => {
      const updates = JSON.parse(event.data) as Record<string, PriceUpdate>;
      setState((current) => applyPriceEvent(current, updates));
    };
    source.onerror = () => {
      const status = source.readyState === EventSource.CLOSED ? "closed" : "reconnecting";
      setState((current) => ({ ...current, status }));
    };
    return () => source.close();
  }, []);

  return state;
}
