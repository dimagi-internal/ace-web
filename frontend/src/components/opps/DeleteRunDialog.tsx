import { deleteOppRun } from "@/api/opps";
import { dropOpp } from "@/api/oppCache";

import { ConfirmDialog } from "./ConfirmDialog";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  oppSlug: string;
  runId: string;
  /** Display label for the run (e.g. "May 9, 4:55 AM"). Falls back to runId. */
  runLabel?: string;
  /** Receives the just-deleted runId so the caller can compare it to the URL-pinned run. */
  onDeleted?: (runId: string) => void;
}

/**
 * Trash a single run subfolder. Lighter confirmation than DeleteOppDialog
 * (no type-to-confirm) — Drive trash is 30-day recoverable and the
 * blast radius is one run, not a whole opp.
 */
export function DeleteRunDialog({
  open,
  onOpenChange,
  oppSlug,
  runId,
  runLabel,
  onDeleted,
}: Props) {
  const display = runLabel ?? runId;

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Trash run ${display}?`}
      description={
        <>
          Moves{" "}
          <code className="font-mono">ACE/{oppSlug}/runs/{runId}</code> to
          Google Drive's trash (30-day recoverable). The opp itself stays.
          Linked chat sessions are kept too — they're useful as transcript
          history even after the run folder is gone.
        </>
      }
      destructive
      confirmLabel="Trash run"
      confirmingLabel="Trashing…"
      successToast={`Trashed run ${display}`}
      errorToastPrefix="Trash failed"
      onConfirm={async () => {
        await deleteOppRun(oppSlug, runId);
        // Drop the in-memory opp cache so the next snapshot fetch hits
        // the server (which will re-list the runs/ folder from Drive
        // minus this run).
        dropOpp(oppSlug);
        onDeleted?.(runId);
      }}
    />
  );
}
