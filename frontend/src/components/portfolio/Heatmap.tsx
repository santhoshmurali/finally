import { buildHeatmap } from "@/lib/heatmap";
import type { LiveValuation } from "@/lib/valuation";

interface HeatmapProps {
  valuation: LiveValuation | null;
}

/** Portfolio treemap: tiles sized by share of total value (cash included), coloured by P&L. */
export function Heatmap({ valuation }: HeatmapProps) {
  const tiles = valuation ? buildHeatmap(valuation) : [];
  return (
    <section data-testid="heatmap" className="flex min-h-0 flex-col bg-terminal-panel">
      <header className="border-b border-terminal-border px-3 py-2 text-xs uppercase tracking-wide text-terminal-muted">
        Portfolio heatmap
      </header>
      <div className="relative m-2 min-h-56 flex-1">
        {tiles.map((tile) => (
          <div
            key={tile.id}
            data-testid="heatmap-tile"
            data-ticker={tile.id}
            data-pnl={tile.pnl}
            title={`${tile.id}: ${tile.detail}`}
            className="@container absolute overflow-hidden border border-terminal-bg p-1.5 text-xs font-semibold"
            style={{
              left: `${tile.x * 100}%`,
              top: `${tile.y * 100}%`,
              width: `${tile.width * 100}%`,
              height: `${tile.height * 100}%`,
              backgroundColor: tile.color,
            }}
          >
            {/* Labels show only when the tile is wide enough to hold them; the title keeps the detail. */}
            <div className="hidden h-full flex-col justify-between @[5rem]:flex">
              <span className="truncate">{tile.id}</span>
              <span className="truncate font-mono font-normal">{tile.detail}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
