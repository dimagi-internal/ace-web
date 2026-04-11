import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";

import { useCliAuthStatus } from "../hooks/useCliAuthStatus";

export function CliAuthBanner() {
  const authenticated = useCliAuthStatus();
  if (authenticated !== false) return null;
  return (
    <div className="flex items-center gap-2 border-b border-border bg-muted px-4 py-2 text-sm text-muted-foreground">
      <AlertTriangle className="h-4 w-4 text-foreground/60" />
      <span>
        Claude CLI is not connected.{" "}
        <Link to="/auth/cli" className="font-medium text-primary underline-offset-4 hover:underline">
          Connect now →
        </Link>
      </span>
    </div>
  );
}
