import { Link } from "react-router-dom";

interface Props {
  wsConnected: boolean;
  cliAuthenticated: boolean | null;
}

export function ConnectionStatus({ wsConnected, cliAuthenticated }: Props) {
  if (cliAuthenticated === false) {
    return (
      <Link
        to="/auth/cli"
        className="inline-flex items-center gap-1.5 rounded-full border border-destructive/40 bg-destructive/10 px-2 py-0.5 text-xs text-destructive hover:bg-destructive/20"
        title="Claude CLI is not connected. Click to set up."
      >
        <span className="h-2 w-2 rounded-full bg-destructive" />
        CLI not connected
      </Link>
    );
  }
  if (!wsConnected) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-600 dark:text-amber-400"
        title="Trying to reconnect to the chat server."
      >
        <span className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
        Reconnecting…
      </span>
    );
  }
  if (cliAuthenticated === null) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
        title="Checking Claude CLI…"
      >
        <span className="h-2 w-2 animate-pulse rounded-full bg-muted-foreground" />
        Checking…
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-600 dark:text-emerald-400"
      title="Connected to Claude."
    >
      <span className="h-2 w-2 rounded-full bg-emerald-500" />
      Connected
    </span>
  );
}
