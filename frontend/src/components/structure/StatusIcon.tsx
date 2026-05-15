import { AlertTriangle, CircleDashed } from "lucide-react";

import type { StructureStatus } from "../../api/types.ws";

// Only renders for non-ok states. 90% of rows are "ok" — drawing a green check
// on every one of them was visual noise that buried the rare meaningful signal.
// Errors stay pinned to the row that caused them (no roll-up to skill/phase),
// so the yellow ⚠ here means "this specific tool call returned is_error".
export function StatusIcon({ status }: { status: StructureStatus }) {
  if (status === "error") {
    return (
      <AlertTriangle
        className="h-3.5 w-3.5 text-yellow-500 shrink-0"
        aria-label="error"
      />
    );
  }
  if (status === "incomplete") {
    return (
      <CircleDashed
        className="h-3.5 w-3.5 text-muted-foreground shrink-0"
        aria-label="incomplete"
      />
    );
  }
  return null;
}
