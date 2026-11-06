import { formatPercent } from "@/lib/format";
import { layoutTreemap, type Tile } from "@/lib/treemap";
import type { LivePortfolio } from "@/lib/ticks";

const WIDTH = 1000;
const HEIGHT = 380;
const CASH_COLOR = "#30363d";

interface Cell {
  label: string;
  value: number;
  pnlPercent: number | null;
}

/** Positions sized by market value and coloured by unrealized P&L; cash is a grey tile. */
export function PortfolioHeatmap({ portfolio }: { portfolio: LivePortfolio }) {
  const cells: Cell[] = [
    { label: "CASH", value: portfolio.cash_balance, pnlPercent: null },
    ...portfolio.positions.map((position) => ({
      label: position.ticker,
      value: position.live_market_value,
      pnlPercent: position.live_unrealized_pnl_percent,
    })),
  ];
  const tiles = layoutTreemap(
    cells.map((cell) => ({ item: cell, weight: cell.value })),
    WIDTH,
    HEIGHT,
  );

  return (
    <section aria-label="Portfolio heatmap" className="flex min-h-0 flex-col">
      <h2 className="panel-title">Heatmap</h2>
      <div className="flex-1 p-2">
        <svg
          data-testid="heatmap"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-full max-h-[320px] w-full"
          role="img"
          aria-label="Positions sized by value and coloured by P&L"
        >
          {tiles.map((tile) => (
            <HeatTile key={tile.item.label} tile={tile} />
          ))}
        </svg>
      </div>
    </section>
  );
}

function HeatTile({ tile }: { tile: Tile<Cell> }) {
  const { item, x, y, width, height } = tile;
  const fill = tileFill(item.pnlPercent);
  const showText = width > 70 && height > 36;
  return (
    <g data-testid={`tile-${item.label}`} data-pnl={item.pnlPercent ?? "cash"}>
      <rect
        x={x + 1}
        y={y + 1}
        width={Math.max(0, width - 2)}
        height={Math.max(0, height - 2)}
        rx={3}
        fill={fill}
      />
      {showText && (
        <>
          <text x={x + 8} y={y + 20} fontSize={16} fontWeight={600} fill="#e6edf3">
            {item.label}
          </text>
          {item.pnlPercent !== null && (
            <text x={x + 8} y={y + 38} fontSize={13} fill="#e6edf3">
              {formatPercent(item.pnlPercent)}
            </text>
          )}
        </>
      )}
    </g>
  );
}

/** Green for gains, red for losses, deeper with larger moves. Cash stays neutral grey. */
export function tileFill(pnlPercent: number | null): string {
  if (pnlPercent === null) return CASH_COLOR;
  const strength = Math.min(Math.max(Math.abs(pnlPercent) / 5, 0.3), 1);
  return pnlPercent >= 0
    ? `rgba(63, 185, 80, ${strength.toFixed(2)})`
    : `rgba(248, 81, 73, ${strength.toFixed(2)})`;
}
