"use client";

import { useState, type FormEvent } from "react";
import { addWatchlistTicker, errorMessage, removeWatchlistTicker } from "@/lib/api";
import type { PriceHistory } from "@/lib/priceHistory";
import type { PriceUpdate, WatchlistItem } from "@/lib/types";
import { WatchlistRow } from "./WatchlistRow";

interface WatchlistProps {
  items: WatchlistItem[];
  prices: Record<string, PriceUpdate>;
  history: PriceHistory;
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  onChange: () => void;
}

/** The watchlist panel: streamed prices, add and remove controls, row selection. */
export function Watchlist({ items, prices, history, selectedTicker, onSelect, onChange }: WatchlistProps) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function mutate(action: () => Promise<unknown>): Promise<boolean> {
    setError(null);
    try {
      await action();
      onChange();
      return true;
    } catch (caught) {
      setError(errorMessage(caught));
      return false;
    }
  }

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ticker = draft.trim().toUpperCase();
    if (ticker && (await mutate(() => addWatchlistTicker(ticker)))) {
      setDraft("");
    }
  }

  return (
    <section data-testid="watchlist-panel" className="flex min-h-0 flex-col bg-terminal-panel">
      <header className="border-b border-terminal-border px-3 py-2 text-xs uppercase tracking-wide text-terminal-muted">
        Watchlist
      </header>
      <form onSubmit={handleAdd} className="flex gap-2 border-b border-terminal-border p-2">
        <input
          data-testid="watchlist-add-input"
          aria-label="Ticker to add"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Add ticker"
          className="min-w-0 flex-1 rounded border border-terminal-border bg-terminal-bg px-2 py-1 uppercase outline-none focus:border-primary"
        />
        <button
          data-testid="watchlist-add-button"
          type="submit"
          className="rounded bg-primary px-3 py-1 font-semibold text-terminal-bg"
        >
          Add
        </button>
      </form>
      {error && (
        <p data-testid="watchlist-error" role="alert" className="px-3 py-1 text-xs text-loss">
          {error}
        </p>
      )}
      <ul className="overflow-y-auto overflow-x-hidden">
        {items.map((item) => (
          <WatchlistRow
            key={item.ticker}
            item={item}
            update={prices[item.ticker]}
            points={history[item.ticker] ?? []}
            selected={item.ticker === selectedTicker}
            onSelect={() => onSelect(item.ticker)}
            onRemove={() => mutate(() => removeWatchlistTicker(item.ticker))}
          />
        ))}
      </ul>
    </section>
  );
}
