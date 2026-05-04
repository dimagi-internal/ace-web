import { useEffect, useState } from "react";
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
  const [confirmText, setConfirmText] = useState("");

  // Reset the confirm input every time the dialog opens — otherwise a
  // stale value from a previous open would let the user one-click delete.
  useEffect(() => {
    if (open) setConfirmText("");
  }, [open]);

  const canDelete = confirmText.trim() === slug;

  async function handleDelete() {
    if (!canDelete) return;
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
        {/* Type-to-confirm: the trash icon on opp cards is now always
            visible (round 2), making accidental clicks more likely. The
            destructive action should require an unambiguous confirmation
            keystroke, not just a button click. */}
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="confirm-delete-slug"
            className="text-xs text-muted-foreground"
          >
            Type the opp ID{" "}
            <code className="font-mono text-foreground">{slug}</code>{" "}
            to confirm:
          </label>
          <input
            id="confirm-delete-slug"
            type="text"
            autoComplete="off"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder={slug}
            disabled={submitting}
            className="rounded border border-input bg-card px-2 py-1 text-sm font-mono text-foreground focus:border-ring focus:outline-none"
          />
        </div>
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
            disabled={submitting || !canDelete}
            title={canDelete ? undefined : "Type the opp ID to enable delete"}
          >
            {submitting ? "Deleting..." : "Delete opp"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
