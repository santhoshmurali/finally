import { useCallback, useEffect, useState } from "react";
import { errorMessage, getPortfolio, getPortfolioHistory, getWatchlist } from "@/lib/api";
import type { Portfolio, Snapshot, WatchlistItem } from "@/lib/types";

/** How often the account is re-read, matching the backend snapshot interval. */
export const REFRESH_INTERVAL_MS = 30_000;

export interface Account {
  watchlist: WatchlistItem[];
  portfolio: Portfolio | null;
  snapshots: Snapshot[];
}

export interface AccountData extends Account {
  /** Message from the last failed load, or null once a load succeeds. */
  error: string | null;
  refresh: () => Promise<void>;
}

const EMPTY_ACCOUNT: Account = { watchlist: [], portfolio: null, snapshots: [] };

function loadAccount(): Promise<Account> {
  return Promise.all([getWatchlist(), getPortfolio(), getPortfolioHistory()]).then(
    ([watchlist, portfolio, snapshots]) => ({ watchlist, portfolio, snapshots }),
  );
}

/** Loads the watchlist, portfolio and value history; reloads on an interval and on demand. */
export function useAccountData(): AccountData {
  const [account, setAccount] = useState(EMPTY_ACCOUNT);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    () =>
      loadAccount().then(
        (next) => {
          setAccount(next);
          setError(null);
        },
        (caught) => setError(errorMessage(caught)),
      ),
    [],
  );

  useEffect(() => {
    const poll = () => void refresh();
    poll();
    const timer = setInterval(poll, REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  return { ...account, error, refresh };
}
