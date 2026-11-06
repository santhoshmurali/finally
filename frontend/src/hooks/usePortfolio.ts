"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Portfolio } from "@/lib/types";

const REFRESH_MS = 2000;

export interface PortfolioState {
  portfolio: Portfolio | null;
  error: string | null;
  refresh: () => Promise<void>;
}

/** Cash and positions, re-read every few seconds and after each trade via `refresh`. */
export function usePortfolio(intervalMs: number = REFRESH_MS): PortfolioState {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setPortfolio(await api.portfolio());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Portfolio unavailable");
    }
  }, []);

  useEffect(() => {
    let active = true;
    const load = () =>
      api.portfolio().then(
        (next) => {
          if (!active) return;
          setPortfolio(next);
          setError(null);
        },
        (caught: unknown) => {
          if (active) setError(caught instanceof Error ? caught.message : "Portfolio unavailable");
        },
      );
    void load();
    const timer = setInterval(() => void load(), intervalMs);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [intervalMs]);

  return { portfolio, error, refresh };
}
