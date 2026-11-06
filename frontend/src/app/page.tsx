"use client";

import { useCallback, useEffect, useState } from "react";
import { ChatPanel } from "@/components/ChatPanel";
import { Header } from "@/components/Header";
import { MainChart } from "@/components/MainChart";
import { PnlChart } from "@/components/PnlChart";
import { PortfolioHeatmap } from "@/components/PortfolioHeatmap";
import { PositionsTable } from "@/components/PositionsTable";
import { TradeBar } from "@/components/TradeBar";
import { WatchlistPanel } from "@/components/WatchlistPanel";
import { api } from "@/lib/api";
import { valueAtLivePrices } from "@/lib/ticks";
import type { SnapshotPoint } from "@/lib/types";
import { usePortfolio } from "@/hooks/usePortfolio";
import { usePriceStream } from "@/hooks/usePriceStream";
import { useWatchlist } from "@/hooks/useWatchlist";

const SNAPSHOT_REFRESH_MS = 30_000;

export default function Dashboard() {
  const stream = usePriceStream();
  const {
    portfolio: account,
    error: portfolioError,
    refresh: refreshPortfolio,
  } = usePortfolio();
  const {
    entries,
    error: watchlistError,
    add: addToWatchlist,
    remove: removeFromWatchlist,
    refresh: refreshWatchlist,
  } = useWatchlist();
  const [selected, setSelected] = useState("");
  const [snapshots, setSnapshots] = useState<SnapshotPoint[]>([]);

  const selectedTicker = entries.some((entry) => entry.ticker === selected)
    ? selected
    : (entries[0]?.ticker ?? "");

  useEffect(() => {
    let active = true;
    const load = () =>
      api.history().then(
        (points) => {
          if (active) setSnapshots(points);
        },
        () => undefined, // The chart keeps its last data; the next interval retries.
      );
    void load();
    const timer = setInterval(() => void load(), SNAPSHOT_REFRESH_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  const refreshAfterTrade = useCallback(async () => {
    await Promise.all([
      refreshPortfolio(),
      refreshWatchlist(),
      api.history().then(setSnapshots, () => undefined),
    ]);
  }, [refreshPortfolio, refreshWatchlist]);

  const live = account ? valueAtLivePrices(account, stream.prices) : null;

  return (
    <div className="flex min-h-dvh flex-col">
      <Header
        totalValue={live?.total_value ?? null}
        cashBalance={live?.cash_balance ?? null}
        status={stream.status}
      />
      <div className="grid flex-1 grid-cols-1 lg:grid-cols-[260px_minmax(0,1fr)_320px]">
        <WatchlistPanel
          entries={entries}
          prices={stream.prices}
          history={stream.history}
          selected={selectedTicker}
          error={watchlistError}
          onSelect={setSelected}
          onAdd={async (ticker) => {
            const added = await addToWatchlist(ticker);
            if (added) setSelected(ticker.trim().toUpperCase());
            return added;
          }}
          onRemove={removeFromWatchlist}
        />

        <main className="flex min-w-0 flex-col">
          <div className="min-h-[280px] border-b border-line">
            <MainChart ticker={selectedTicker} points={stream.history[selectedTicker] ?? []} />
          </div>
          <TradeBar key={selectedTicker} ticker={selectedTicker} onTraded={refreshAfterTrade} />
          {live && (
            <div className="grid grid-cols-1 border-t border-line xl:grid-cols-2">
              <div className="border-b border-line xl:border-b-0 xl:border-r">
                <PortfolioHeatmap portfolio={live} />
              </div>
              <div className="flex flex-col">
                <PnlChart snapshots={snapshots} />
              </div>
            </div>
          )}
          {live && <PositionsTable portfolio={live} />}
          {portfolioError && (
            <p role="alert" className="p-3 text-sm text-loss">
              {portfolioError}
            </p>
          )}
        </main>

        <ChatPanel onActionsApplied={refreshAfterTrade} />
      </div>
    </div>
  );
}
