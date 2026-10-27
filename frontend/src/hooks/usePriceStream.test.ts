import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeUpdate } from "@/test/factories";
import { applyPriceEvent, INITIAL_PRICE_STREAM, PRICE_STREAM_URL, usePriceStream } from "./usePriceStream";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
}

function latestSource(): FakeEventSource {
  return FakeEventSource.instances[FakeEventSource.instances.length - 1];
}

describe("applyPriceEvent", () => {
  it("merges prices and extends the history of each ticker", () => {
    const update = makeUpdate("TCS", 2529, { timestamp: 50 });
    const state = applyPriceEvent(INITIAL_PRICE_STREAM, { TCS: update });
    expect(state.prices.TCS).toEqual(update);
    expect(state.history.TCS).toEqual([{ time: 50, value: 2529 }]);
    expect(state.status).toBe("open");
  });
});

describe("usePriceStream", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens the price stream URL and starts as reconnecting", () => {
    const { result } = renderHook(() => usePriceStream());
    expect(latestSource().url).toBe(PRICE_STREAM_URL);
    expect(result.current.status).toBe("reconnecting");
  });

  it("reports open, then streamed prices", () => {
    const { result } = renderHook(() => usePriceStream());
    act(() => latestSource().onopen?.());
    expect(result.current.status).toBe("open");

    const payload = { TCS: makeUpdate("TCS", 2530, { timestamp: 60, direction: "up" }) };
    act(() => latestSource().onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>));
    expect(result.current.prices.TCS.price).toBe(2530);
    expect(result.current.history.TCS).toHaveLength(1);
  });

  it("reports reconnecting while the browser retries, and closed once it gives up", () => {
    const { result } = renderHook(() => usePriceStream());
    act(() => latestSource().onerror?.());
    expect(result.current.status).toBe("reconnecting");

    act(() => {
      latestSource().readyState = FakeEventSource.CLOSED;
      latestSource().onerror?.();
    });
    expect(result.current.status).toBe("closed");
  });

  it("closes the source on unmount", () => {
    const { unmount } = renderHook(() => usePriceStream());
    const source = latestSource();
    unmount();
    expect(source.closed).toBe(true);
  });
});
