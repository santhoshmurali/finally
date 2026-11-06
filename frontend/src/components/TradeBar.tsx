"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { formatPrice, formatQuantity } from "@/lib/format";
import type { Side, TradeResult } from "@/lib/types";

interface TradeBarProps {
  ticker: string;
  onTraded: () => void;
}

/** Market order entry: ticker, quantity, then buy or sell at the current price. */
export function TradeBar({ ticker, onTraded }: TradeBarProps) {
  const [symbol, setSymbol] = useState(ticker);
  const [quantity, setQuantity] = useState("1");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);

  async function trade(side: Side) {
    const amount = Number(quantity);
    setBusy(true);
    setFeedback(null);
    try {
      const result: TradeResult = await api.trade(symbol.trim().toUpperCase(), amount, side);
      setFeedback({
        ok: true,
        text: `${side === "buy" ? "Bought" : "Sold"} ${formatQuantity(result.quantity)} ${result.ticker} at ${formatPrice(result.price)}`,
      });
      onTraded();
    } catch (caught) {
      setFeedback({ ok: false, text: caught instanceof Error ? caught.message : "Trade failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Trade" className="border-t border-line p-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-xs text-muted">
          Ticker
          <input
            aria-label="Trade ticker"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            className="input w-32 uppercase"
          />
        </label>
        <label className="flex flex-col text-xs text-muted">
          Quantity
          <input
            aria-label="Trade quantity"
            type="number"
            min="0"
            step="any"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            className="input w-28"
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={() => void trade("buy")}
          className="btn-buy"
        >
          Buy
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void trade("sell")}
          className="btn-sell"
        >
          Sell
        </button>
        {feedback && (
          <p role={feedback.ok ? "status" : "alert"} className={`text-sm ${feedback.ok ? "text-gain" : "text-loss"}`}>
            {feedback.text}
          </p>
        )}
      </div>
    </section>
  );
}
