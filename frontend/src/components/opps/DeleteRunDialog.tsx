import { useState } from "react";
import { toast } from "sonner";

import { deleteOppRun } from "@/api/opps";
import { dropOpp } from "@/api/oppCache";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  oppSlug: string;
  runId: string;
  /** Display label for the run (e.g. "May 9, 4:55 AM"). Falls back to runId. */
  runLabel?: string;
  onDeleted?: () => void;
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
  const [submitting, setSubmitting] = useState(false);
  const display = runLabel ?? runId;

  async function handleDelete() {
    setSubmitting(true);
    try {
      await deleteOppRun(oppSlug, runId);
      // Drop the in-memory opp cache so the next snapshot fetch hits the
      // server (which will re-list the runs/ folder from Drive minus
      // this run).
      dropOpp(oppSlug);
      toast.success(`Trashed run ${display}`);
      onOpenChange(false);
      onDeleted?.();
    } catch (e) {
      toast.error(`Trash failed: ${String((e as Error).message ?? e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Trash run {display}?</DialogTitle>
          <DialogDescription>
            Moves <code className="font-mono">ACE/{oppSlug}/runs/{runId}</code>{" "}
            to Google Drive's trash (30-day recoverable). The opp itself
            stays. Linked chat sessions are kept too — they're useful as
            transcript history even after the run folder is gone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={submitting}
          >
            {submitting ? "Trashing…" : "Trash run"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
