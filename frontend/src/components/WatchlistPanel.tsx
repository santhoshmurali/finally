"use client";

import { useState, type FormEvent } from "react";
import { PriceCell } from "@/components/PriceCell";
import { Sparkline } from "@/components/Sparkline";
import { formatPercent } from "@/lib/format";
import type { TickHistory } from "@/lib/ticks";
import type { PriceUpdate, WatchEntry } from "@/lib/types";

interface WatchlistPanelProps {
  entries: WatchEntry[];
  prices: Record<string, PriceUpdate>;
  history: TickHistory;
  selected: string;
  error: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<boolean>;
  onRemove: (ticker: string) => Promise<void>;
}

export function WatchlistPanel({
  entries,
  prices,
  history,
  selected,
  error,
  onSelect,
  onAdd,
  onRemove,
}: WatchlistPanelProps) {
  const [draft, setDraft] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const ticker = draft.trim();
    if (!ticker) return;
    if (await onAdd(ticker)) setDraft("");
  }

  return (
    <section aria-label="Watchlist" className="flex min-h-0 flex-col border-r border-line">
      <h2 className="panel-title">Watchlist</h2>
      <form onSubmit={submit} className="flex gap-2 border-b border-line p-2">
        <input
          aria-label="Ticker to add"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Add NSE symbol"
          className="input flex-1 uppercase"
        />
        <button type="submit" className="btn-secondary">
          Add
        </button>
      </form>
      {error && (
        <p role="alert" className="px-3 py-2 text-xs text-loss">
          {error}
        </p>
      )}
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {entries.map((entry) => {
          const live = prices[entry.ticker];
          const price = live?.price ?? entry.price;
          const dayChange = live?.day_change_percent ?? entry.day_change_percent;
          const values = (history[entry.ticker] ?? []).map((point) => point.value);
          const isSelected = entry.ticker === selected;
          return (
            <li
              key={entry.ticker}
              data-testid={`watch-${entry.ticker}`}
              className={`grid grid-cols-[1fr_auto] items-center gap-x-2 border-b border-line px-3 py-2 text-sm ${
                isSelected ? "bg-panel-hi" : "hover:bg-panel-hi/60"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(entry.ticker)}
                aria-pressed={isSelected}
                className="text-left font-medium text-ink"
              >
                {entry.ticker}
              </button>
              <div className="text-right">
                <PriceCell value={price} />
              </div>
              <span className="text-xs text-muted">
                <Sparkline values={values} positive={(dayChange ?? 0) >= 0} />
              </span>
              <div className="flex items-center justify-end gap-2">
                <span className={`tabular-nums text-xs ${(dayChange ?? 0) >= 0 ? "text-gain" : "text-loss"}`}>
                  {formatPercent(dayChange)}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${entry.ticker}`}
                  onClick={() => void onRemove(entry.ticker)}
                  className="text-muted hover:text-loss"
                >
                  x
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
