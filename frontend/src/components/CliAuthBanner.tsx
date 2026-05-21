import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";

import { useCliAuthStatus } from "../hooks/useCliAuthStatus";

/**
 * Top-of-page banner shown when the server has no Claude CLI blob at all.
 *
 * We deliberately gate this on ``hasBlob === false`` rather than the live
 * ``authenticated`` check: the live check briefly lies after every deploy
 * (cold MCP load > 30s subprocess timeout, see issue #479), and we don't
 * want a banner that contradicts a chat surface that actually works.
 */
export function CliAuthBanner() {
  const { hasBlob } = useCliAuthStatus();
  if (hasBlob !== false) return null;
  return (
    <div className="flex items-center gap-2 border-b border-border bg-muted px-4 py-2 text-sm text-muted-foreground">
      <AlertTriangle className="h-4 w-4 text-foreground/60" />
      <span>
        No Claude CLI credentials uploaded.{" "}
        <Link to="/auth/cli" className="font-medium text-primary underline-offset-4 hover:underline">
          Connect now →
        </Link>
      </span>
    </div>
  );
}
