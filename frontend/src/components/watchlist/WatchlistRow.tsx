import { formatPercent, formatPrice, pnlTextClass } from "@/lib/format";
import type { PricePoint } from "@/lib/priceHistory";
import type { PriceDirection, PriceUpdate, WatchlistItem } from "@/lib/types";
import { Sparkline } from "./Sparkline";

const SPARKLINE_POINTS = 120;

const FLASH_CLASS: Record<PriceDirection, string> = {
  up: "animate-flash-up",
  down: "animate-flash-down",
  flat: "",
};

interface WatchlistRowProps {
  item: WatchlistItem;
  update: PriceUpdate | undefined;
  points: PricePoint[];
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}

/** One watchlist line: live price with flash, day change, sparkline and remove control. */
export function WatchlistRow({ item, update, points, selected, onSelect, onRemove }: WatchlistRowProps) {
  const price = update?.price ?? item.price;
  const dayChange = update?.day_change_percent ?? item.day_change_percent;
  return (
    <li
      data-testid="watchlist-row"
      data-ticker={item.ticker}
      className={`flex items-center border-b border-terminal-border ${selected ? "bg-primary/10" : ""}`}
    >
      <button
        type="button"
        onClick={onSelect}
        className="grid flex-1 grid-cols-[5.5rem_minmax(0,1fr)_4.75rem_4.25rem] items-center gap-2 px-2 py-2 text-left hover:bg-terminal-panel"
      >
        <span className="font-semibold">{item.ticker}</span>
        <Sparkline points={points.slice(-SPARKLINE_POINTS)} />
        <span
          key={update?.timestamp}
          data-testid="watchlist-price"
          data-price={price ?? undefined}
          data-direction={update?.direction ?? "none"}
          className={`rounded px-1 text-right font-mono tabular-nums ${FLASH_CLASS[update?.direction ?? "flat"]}`}
        >
          {price === null ? "--" : formatPrice(price)}
        </span>
        <span data-testid="watchlist-change" className={`text-right font-mono tabular-nums ${pnlTextClass(dayChange ?? 0)}`}>
          {dayChange === null ? "--" : formatPercent(dayChange)}
        </span>
      </button>
      <button
        type="button"
        aria-label={`Remove ${item.ticker}`}
        data-testid="watchlist-remove"
        onClick={onRemove}
        className="px-3 text-terminal-muted hover:text-loss"
      >
        ×
      </button>
    </li>
  );
}
