import { formatINR } from "@/lib/format";
import type { ConnectionStatus } from "@/hooks/usePriceStream";

interface HeaderProps {
  totalValue: number | null;
  cashBalance: number | null;
  status: ConnectionStatus;
}

const STATUS_DOT: Record<ConnectionStatus, string> = {
  open: "bg-gain",
  reconnecting: "bg-accent",
  closed: "bg-loss",
};

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  open: "Live",
  reconnecting: "Reconnecting",
  closed: "Disconnected",
};

/** Top bar: brand, live portfolio value, cash, and the price stream connection dot. */
export function Header({ totalValue, cashBalance, status }: HeaderProps) {
  return (
    <header
      data-testid="header"
      className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-terminal-border bg-terminal-panel px-4 py-2"
    >
      <h1 className="text-lg font-bold tracking-tight text-accent">FinAlly</h1>
      <dl className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
        <div className="flex items-baseline gap-2">
          <dt className="text-xs uppercase text-terminal-muted">Portfolio</dt>
          <dd data-testid="header-total-value" className="font-mono font-semibold tabular-nums">
            {totalValue === null ? "--" : formatINR(totalValue)}
          </dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt className="text-xs uppercase text-terminal-muted">Cash</dt>
          <dd data-testid="header-cash" className="font-mono tabular-nums">
            {cashBalance === null ? "--" : formatINR(cashBalance)}
          </dd>
        </div>
      </dl>
      <div data-testid="connection-status" data-state={status} className="flex items-center gap-2 text-xs text-terminal-muted">
        <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[status]}`} aria-hidden="true" />
        {STATUS_LABEL[status]}
      </div>
    </header>
  );
}
