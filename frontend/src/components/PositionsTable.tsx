import { formatInr, formatPercent, formatPrice, formatQuantity } from "@/lib/format";
import type { LivePortfolio } from "@/lib/ticks";

export function PositionsTable({ portfolio }: { portfolio: LivePortfolio }) {
  return (
    <section aria-label="Positions" className="flex min-h-0 flex-col">
      <h2 className="panel-title">Positions</h2>
      {portfolio.positions.length === 0 ? (
        <p className="p-3 text-sm text-muted">No open positions. Buy a ticker to start.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted">
              <tr>
                <th className="px-3 py-1.5 font-medium">Ticker</th>
                <th className="px-3 py-1.5 text-right font-medium">Qty</th>
                <th className="px-3 py-1.5 text-right font-medium">Avg cost</th>
                <th className="px-3 py-1.5 text-right font-medium">Price</th>
                <th className="px-3 py-1.5 text-right font-medium">Value</th>
                <th className="px-3 py-1.5 text-right font-medium">Unrealized P&amp;L</th>
                <th className="px-3 py-1.5 text-right font-medium">Day</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.positions.map((position) => {
                const pnlClass = position.live_unrealized_pnl >= 0 ? "text-gain" : "text-loss";
                return (
                  <tr key={position.ticker} data-testid={`position-${position.ticker}`} className="border-t border-line">
                    <td className="px-3 py-1.5 font-medium text-ink">{position.ticker}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatQuantity(position.quantity)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPrice(position.avg_cost)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPrice(position.live_price)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatInr(position.live_market_value)}</td>
                    <td className={`px-3 py-1.5 text-right tabular-nums ${pnlClass}`}>
                      {formatInr(position.live_unrealized_pnl)} ({formatPercent(position.live_unrealized_pnl_percent)})
                    </td>
                    <td className={`px-3 py-1.5 text-right tabular-nums ${position.day_change_percent >= 0 ? "text-gain" : "text-loss"}`}>
                      {formatPercent(position.day_change_percent)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
