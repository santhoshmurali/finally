"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { WatchEntry } from "@/lib/types";

export interface WatchlistState {
  entries: WatchEntry[];
  error: string | null;
  add: (ticker: string) => Promise<boolean>;
  remove: (ticker: string) => Promise<void>;
  refresh: () => Promise<void>;
}

/** The watchlist with its latest prices; add and remove re-read the list afterwards. */
export function useWatchlist(): WatchlistState {
  const [entries, setEntries] = useState<WatchEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setEntries(await api.watchlist());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Watchlist unavailable");
    }
  }, []);

  useEffect(() => {
    let active = true;
    api.watchlist().then(
      (next) => {
        if (active) setEntries(next);
      },
      (caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "Watchlist unavailable");
      },
    );
    return () => {
      active = false;
    };
  }, []);

  const add = useCallback(
    async (ticker: string) => {
      try {
        await api.addToWatchlist(ticker);
        setError(null);
        await refresh();
        return true;
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not add ticker");
        return false;
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (ticker: string) => {
      try {
        await api.removeFromWatchlist(ticker);
        setError(null);
        await refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not remove ticker");
      }
    },
    [refresh],
  );

  return { entries, error, add, remove, refresh };
}
