"use client";

import { useMemo, useState } from "react";
import { useAccountData } from "@/hooks/useAccountData";
import { usePriceStream } from "@/hooks/usePriceStream";
import { snapshotPoints } from "@/lib/valueHistory";
import { valuePortfolio } from "@/lib/valuation";
import { ChatPanel } from "./chat/ChatPanel";
import { MainChart, PnlChart } from "./chart/ChartPanels";
import { Header } from "./Header";
import { Heatmap } from "./portfolio/Heatmap";
import { PositionsTable } from "./portfolio/PositionsTable";
import { TradeBar } from "./trade/TradeBar";
import { Watchlist } from "./watchlist/Watchlist";

/** The single-page trading terminal: owns the stream, the account data and the selected ticker. */
export function Dashboard() {
  const stream = usePriceStream();
  const account = useAccountData();
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const chartTicker = selectedTicker ?? account.watchlist[0]?.ticker ?? null;

  const valuation = useMemo(
    () => (account.portfolio ? valuePortfolio(account.portfolio, stream.prices) : null),
    [account.portfolio, stream.prices],
  );
  const valueHistory = useMemo(() => snapshotPoints(account.snapshots), [account.snapshots]);
  const chartPoints = chartTicker ? (stream.history[chartTicker] ?? []) : [];

  return (
    <div className="flex min-h-screen flex-col bg-terminal-border">
      <Header
        totalValue={valuation?.totalValue ?? null}
        cashBalance={valuation?.cashBalance ?? null}
        status={stream.status}
      />
      {account.error && (
        <p data-testid="load-error" role="alert" className="border-b border-terminal-border bg-terminal-panel px-4 py-1 text-xs text-loss">
          Account data failed to load: {account.error}
        </p>
      )}
      <main
        data-testid="app-root"
        className="grid flex-1 grid-cols-1 gap-px lg:grid-cols-[22rem_minmax(0,1fr)_auto]"
      >
        <Watchlist
          items={account.watchlist}
          prices={stream.prices}
          history={stream.history}
          selectedTicker={chartTicker}
          onSelect={setSelectedTicker}
          onChange={account.refresh}
        />
        <div className="flex min-w-0 flex-col gap-px">
          <MainChart ticker={chartTicker} points={chartPoints} />
          <div className="grid grid-cols-1 gap-px xl:grid-cols-2">
            <Heatmap valuation={valuation} />
            <PnlChart points={valueHistory} />
          </div>
          <PositionsTable positions={valuation?.positions ?? []} />
          <TradeBar onTraded={account.refresh} />
        </div>
        <ChatPanel onReply={account.refresh} />
      </main>
    </div>
  );
}
