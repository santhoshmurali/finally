"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { formatPrice, formatQuantity } from "@/lib/format";
import type { ChatEntry, ExecutedTrade, WatchlistChange } from "@/lib/types";

interface ChatPanelProps {
  onActionsApplied: () => void;
}

/** Collapsible assistant panel. Trades and watchlist changes show up inline as confirmations. */
export function ChatPanel({ onActionsApplied }: ChatPanelProps) {
  const [open, setOpen] = useState(true);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);

  async function send(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    setDraft("");
    setEntries((previous) => [...previous, { role: "user", text }]);
    setPending(true);
    try {
      const reply = await api.chat(text);
      setEntries((previous) => [
        ...previous,
        {
          role: "assistant",
          text: reply.message,
          trades: reply.trades,
          watchlist_changes: reply.watchlist_changes,
        },
      ]);
      if (reply.trades || reply.watchlist_changes) onActionsApplied();
    } catch (caught) {
      const reason = caught instanceof Error ? caught.message : "Chat failed";
      setEntries((previous) => [...previous, { role: "assistant", text: `Error: ${reason}` }]);
    } finally {
      setPending(false);
    }
  }

  if (!open) {
    return (
      <aside className="flex h-full items-start justify-center border-l border-line p-2">
        <button type="button" onClick={() => setOpen(true)} className="btn-secondary writing-vertical">
          FinAlly chat
        </button>
      </aside>
    );
  }

  return (
    <aside aria-label="FinAlly chat" className="flex h-full min-h-0 flex-col border-l border-line">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <h2 className="panel-title border-0 p-0">FinAlly chat</h2>
        <button type="button" onClick={() => setOpen(false)} className="text-xs text-muted hover:text-ink">
          Hide
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3" data-testid="chat-log">
        {entries.length === 0 && (
          <p className="text-sm text-muted">Ask about your portfolio, or ask FinAlly to trade or manage the watchlist.</p>
        )}
        {entries.map((entry, index) => (
          <Message key={index} entry={entry} />
        ))}
        {pending && (
          <p role="status" className="text-sm text-muted">
            FinAlly is thinking...
          </p>
        )}
      </div>
      <form onSubmit={send} className="flex gap-2 border-t border-line p-2">
        <input
          aria-label="Chat message"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask FinAlly"
          className="input flex-1"
        />
        <button type="submit" disabled={pending} className="btn-submit">
          Send
        </button>
      </form>
    </aside>
  );
}

function Message({ entry }: { entry: ChatEntry }) {
  const isUser = entry.role === "user";
  return (
    <div className={isUser ? "text-right" : "text-left"}>
      <p
        className={`inline-block max-w-[90%] whitespace-pre-wrap rounded px-3 py-2 text-sm ${
          isUser ? "bg-panel-hi text-ink" : "bg-panel text-ink"
        }`}
      >
        {entry.text}
      </p>
      {entry.trades?.map((trade) => (
        <Confirmation key={`t-${trade.ticker}-${trade.side}-${trade.price}`} text={tradeText(trade)} />
      ))}
      {entry.watchlist_changes?.map((change) => (
        <Confirmation key={`w-${change.ticker}-${change.action}`} text={watchText(change)} />
      ))}
    </div>
  );
}

function Confirmation({ text }: { text: string }) {
  return <p className="mt-1 inline-block rounded border border-accent/40 px-2 py-0.5 text-xs text-accent">{text}</p>;
}

function tradeText(trade: ExecutedTrade): string {
  const verb = trade.side === "buy" ? "Bought" : "Sold";
  return `${verb} ${formatQuantity(trade.quantity)} ${trade.ticker} at ${formatPrice(trade.price)}`;
}

function watchText(change: WatchlistChange): string {
  return change.action === "add" ? `Added ${change.ticker} to watchlist` : `Removed ${change.ticker} from watchlist`;
}
