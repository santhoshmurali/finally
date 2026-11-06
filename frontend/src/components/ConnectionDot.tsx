import type { ConnectionStatus } from "@/lib/types";

const COLORS: Record<ConnectionStatus, string> = {
  connected: "bg-gain",
  reconnecting: "bg-warn",
  disconnected: "bg-loss",
};

export function ConnectionDot({ status }: { status: ConnectionStatus }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted" role="status">
      <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${COLORS[status]}`} />
      <span data-testid="connection-status">{status}</span>
    </span>
  );
}
