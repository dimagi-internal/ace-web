import { CheckCircle2, XCircle, CircleDashed } from "lucide-react";

import type { StructureStatus } from "../../api/types.ws";

export function StatusIcon({ status }: { status: StructureStatus }) {
  if (status === "error") return <XCircle className="h-4 w-4 text-destructive" aria-label="error" />;
  if (status === "incomplete") return <CircleDashed className="h-4 w-4 text-muted-foreground" aria-label="incomplete" />;
  return <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-label="ok" />;
}
