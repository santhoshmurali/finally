import { formatINR, formatQuantity } from "@/lib/format";
import type { ChatMessage, Trade, WatchlistChange } from "@/lib/types";

interface ChatMessageViewProps {
  message: ChatMessage;
}

function tradeLine(trade: Trade): string {
  return `${trade.side} ${formatQuantity(trade.quantity)} ${trade.ticker} @ ${formatINR(trade.price)}`;
}

function watchlistLine(change: WatchlistChange): string {
  return change.action === "add" ? `Added ${change.ticker} to watchlist` : `Removed ${change.ticker} from watchlist`;
}

/** One chat bubble, with trade and watchlist confirmations shown inline under assistant replies. */
export function ChatMessageView({ message }: ChatMessageViewProps) {
  const isUser = message.role === "user";
  const trades = message.actions?.trades ?? [];
  const watchlistChanges = message.actions?.watchlist_changes ?? [];
  return (
    <div data-testid="chat-message" data-role={message.role} className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
      <p
        className={`max-w-full whitespace-pre-wrap rounded px-3 py-2 text-sm ${isUser ? "bg-primary/20" : "bg-terminal-bg"}`}
      >
        {message.content}
      </p>
      {trades.map((trade) => (
        <p key={trade.id} data-testid="chat-trade" className="text-xs font-mono text-accent">
          {tradeLine(trade)}
        </p>
      ))}
      {watchlistChanges.map((change, index) => (
        <p key={`${change.ticker}-${index}`} data-testid="chat-watchlist-change" className="text-xs text-primary">
          {watchlistLine(change)}
        </p>
      ))}
    </div>
  );
}
