import { formatPercent, formatPrice, formatQuantity, formatSignedINR, pnlTextClass } from "@/lib/format";
import type { LivePosition } from "@/lib/valuation";

interface PositionsTableProps {
  positions: LivePosition[];
}

const HEADERS = ["Ticker", "Qty", "Avg cost", "Price", "Unrealized P&L", "Day %"];

/** All open positions with live price, unrealized P&L and the day change. */
export function PositionsTable({ positions }: PositionsTableProps) {
  return (
    <section data-testid="positions-table" className="flex min-h-0 flex-col bg-terminal-panel">
      <header className="border-b border-terminal-border px-3 py-2 text-xs uppercase tracking-wide text-terminal-muted">
        Positions
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-terminal-muted">
            <tr>
              {HEADERS.map((header) => (
                <th key={header} className="px-3 py-1.5 text-right first:text-left">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {positions.length === 0 && (
              <tr>
                <td colSpan={HEADERS.length} className="px-3 py-3 text-center font-sans text-terminal-muted">
                  No open positions
                </td>
              </tr>
            )}
            {positions.map((position) => (
              <tr
                key={position.ticker}
                data-testid="position-row"
                data-ticker={position.ticker}
                className="border-t border-terminal-border"
              >
                <td className="px-3 py-1.5 font-sans font-semibold">{position.ticker}</td>
                <td data-testid="position-quantity" className="px-3 py-1.5 text-right">{formatQuantity(position.quantity)}</td>
                <td className="px-3 py-1.5 text-right">{formatPrice(position.avgCost)}</td>
                <td className="px-3 py-1.5 text-right">{formatPrice(position.price)}</td>
                <td className={`px-3 py-1.5 text-right ${pnlTextClass(position.unrealizedPnl)}`}>
                  {formatSignedINR(position.unrealizedPnl)}
                </td>
                <td className={`px-3 py-1.5 text-right ${pnlTextClass(position.dayChangePercent)}`}>
                  {formatPercent(position.dayChangePercent)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
