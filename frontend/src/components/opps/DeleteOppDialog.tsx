import { useState } from "react";
import { toast } from "sonner";

import { deleteOpp } from "@/api/opps";
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
  slug: string;
  displayName: string;
  onDeleted?: () => void;
}

export function DeleteOppDialog({
  open,
  onOpenChange,
  slug,
  displayName,
  onDeleted,
}: Props) {
  const [submitting, setSubmitting] = useState(false);

  async function handleDelete() {
    setSubmitting(true);
    try {
      await deleteOpp(slug);
      toast.success(`Deleted ${displayName}`);
      onOpenChange(false);
      onDeleted?.();
    } catch (e) {
      toast.error(`Delete failed: ${String((e as Error).message ?? e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete {displayName}?</DialogTitle>
          <DialogDescription>
            This moves <code className="font-mono">ACE/{slug}</code> to
            Google Drive's trash (recoverable for 30 days) and deletes any
            chat sessions linked to this opp. Cannot be undone from ace-web.
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
            {submitting ? "Deleting..." : "Delete opp"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
