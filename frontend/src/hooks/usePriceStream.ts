"use client";

import { useEffect, useState } from "react";
import { appendTicks, type TickHistory } from "@/lib/ticks";
import type { ConnectionStatus, PriceUpdate } from "@/lib/types";

export interface PriceStream {
  prices: Record<string, PriceUpdate>;
  history: TickHistory;
  status: ConnectionStatus;
}

/**
 * Live prices from the SSE endpoint. The browser's EventSource reconnects on its own;
 * this hook only reports the state and keeps the tick history since page load.
 */
export function usePriceStream(url: string = "/api/stream/prices"): PriceStream {
  const [prices, setPrices] = useState<Record<string, PriceUpdate>>({});
  const [history, setHistory] = useState<TickHistory>({});
  const [status, setStatus] = useState<ConnectionStatus>("reconnecting");

  useEffect(() => {
    const source = new EventSource(url);
    source.onopen = () => setStatus("connected");
    source.onerror = () =>
      setStatus(source.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
    source.onmessage = (event: MessageEvent<string>) => {
      const update = JSON.parse(event.data) as Record<string, PriceUpdate>;
      setPrices(update);
      setHistory((previous) => appendTicks(previous, update));
    };
    return () => source.close();
  }, [url]);

  return { prices, history, status };
}
