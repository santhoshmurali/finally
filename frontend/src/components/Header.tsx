import { ConnectionDot } from "@/components/ConnectionDot";
import { formatInr } from "@/lib/format";
import type { ConnectionStatus } from "@/lib/types";

interface HeaderProps {
  totalValue: number | null;
  cashBalance: number | null;
  status: ConnectionStatus;
}

export function Header({ totalValue, cashBalance, status }: HeaderProps) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-4 py-3">
      <div className="flex items-baseline gap-3">
        <h1 className="text-lg font-semibold tracking-wide text-accent">FinAlly</h1>
        <span className="text-xs text-muted">Finance Ally</span>
      </div>
      <div className="flex flex-wrap items-center gap-6 text-sm">
        <Stat label="Portfolio" value={formatInr(totalValue)} testId="total-value" />
        <Stat label="Cash" value={formatInr(cashBalance)} testId="cash-balance" />
        <ConnectionDot status={status} />
      </div>
    </header>
  );
}

function Stat({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-muted">{label}</span>
      <span data-testid={testId} className="tabular-nums font-medium text-ink">
        {value}
      </span>
    </div>
  );
}
