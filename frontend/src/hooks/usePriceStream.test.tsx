import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePriceStream } from "./usePriceStream";
import type { PriceUpdate } from "@/lib/types";

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = FakeEventSource.CLOSED;
  });

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }
}

function quote(ticker: string, price: number, timestamp: number): PriceUpdate {
  return {
    ticker,
    price,
    previous_price: price,
    previous_close: price,
    timestamp,
    change: 0,
    direction: "flat",
    day_change: 0,
    day_change_percent: 0,
  };
}

describe("usePriceStream", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("reports connected once the stream opens and accumulates ticks", () => {
    const { result } = renderHook(() => usePriceStream("/api/stream/prices"));
    const source = FakeEventSource.instances[0];
    expect(source.url).toBe("/api/stream/prices");
    expect(result.current.status).toBe("reconnecting");

    act(() => source.onopen?.());
    expect(result.current.status).toBe("connected");

    act(() =>
      source.onmessage?.({
        data: JSON.stringify({ TCS: quote("TCS", 2500, 1000.2) }),
      } as MessageEvent<string>),
    );
    act(() =>
      source.onmessage?.({
        data: JSON.stringify({ TCS: quote("TCS", 2510, 1001.7) }),
      } as MessageEvent<string>),
    );

    expect(result.current.prices.TCS.price).toBe(2510);
    expect(result.current.history.TCS.map((point) => point.value)).toEqual([2500, 2510]);
  });

  it("reports reconnecting while retrying and disconnected once the browser gives up", () => {
    const { result } = renderHook(() => usePriceStream());
    const source = FakeEventSource.instances[0];
    act(() => source.onopen?.());

    source.readyState = FakeEventSource.OPEN;
    act(() => source.onerror?.());
    expect(result.current.status).toBe("reconnecting");

    source.readyState = FakeEventSource.CLOSED;
    act(() => source.onerror?.());
    expect(result.current.status).toBe("disconnected");
  });

  it("closes the stream on unmount", () => {
    const { unmount } = renderHook(() => usePriceStream());

    unmount();

    expect(FakeEventSource.instances[0].close).toHaveBeenCalledTimes(1);
  });
});
