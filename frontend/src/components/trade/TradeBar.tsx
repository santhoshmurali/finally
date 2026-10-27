"use client";

import { useState } from "react";
import { errorMessage, postTrade } from "@/lib/api";
import { formatINR, formatQuantity } from "@/lib/format";
import type { Side } from "@/lib/types";

interface TradeBarProps {
  onTraded: () => void;
}

interface Notice {
  tone: "ok" | "error";
  text: string;
}

const PAST_TENSE: Record<Side, string> = { buy: "Bought", sell: "Sold" };

const FIELD_LABEL = "flex flex-col gap-1 text-xs uppercase text-terminal-muted";
const FIELD_INPUT = "w-32 rounded border border-terminal-border bg-terminal-bg px-2 py-1 text-terminal-text outline-none focus:border-primary";

/** Market-order entry: ticker and quantity, then buy or sell at the current price. */
export function TradeBar({ onTraded }: TradeBarProps) {
  const [ticker, setTicker] = useState("");
  const [quantity, setQuantity] = useState("");
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const shares = Number(quantity);
  const canTrade = ticker.trim() !== "" && shares > 0 && !pending;

  async function trade(side: Side) {
    setPending(true);
    setNotice(null);
    try {
      const { trade: fill } = await postTrade(ticker.trim().toUpperCase(), shares, side);
      const text = `${PAST_TENSE[side]} ${formatQuantity(fill.quantity)} ${fill.ticker} @ ${formatINR(fill.price)}`;
      setNotice({ tone: "ok", text });
      onTraded();
    } catch (caught) {
      setNotice({ tone: "error", text: errorMessage(caught) });
    } finally {
      setPending(false);
    }
  }

  return (
    <section data-testid="trade-bar" className="flex flex-wrap items-end gap-3 bg-terminal-panel p-3">
      <label className={FIELD_LABEL}>
        Ticker
        <input
          data-testid="trade-ticker"
          value={ticker}
          onChange={(event) => setTicker(event.target.value)}
          className={`${FIELD_INPUT} uppercase`}
        />
      </label>
      <label className={FIELD_LABEL}>
        Quantity
        <input
          data-testid="trade-quantity"
          type="number"
          min="0"
          step="any"
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          className={`${FIELD_INPUT} font-mono`}
        />
      </label>
      <button
        data-testid="trade-buy"
        type="button"
        disabled={!canTrade}
        onClick={() => trade("buy")}
        className="rounded bg-primary px-5 py-1.5 font-semibold text-terminal-bg disabled:opacity-40"
      >
        Buy
      </button>
      <button
        data-testid="trade-sell"
        type="button"
        disabled={!canTrade}
        onClick={() => trade("sell")}
        className="rounded bg-accent px-5 py-1.5 font-semibold text-terminal-bg disabled:opacity-40"
      >
        Sell
      </button>
      {notice && (
        <p
          data-testid="trade-message"
          data-tone={notice.tone}
          role={notice.tone === "error" ? "alert" : "status"}
          className={`text-sm ${notice.tone === "error" ? "text-loss" : "text-terminal-text"}`}
        >
          {notice.text}
        </p>
      )}
    </section>
  );
}
