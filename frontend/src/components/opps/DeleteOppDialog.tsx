import { useEffect, useState } from "react";

import { deleteOpp } from "@/api/opps";

import { ConfirmDialog } from "./ConfirmDialog";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  workspaceSlug: string;
  slug: string;
  displayName: string;
  onDeleted?: () => void;
}

export function DeleteOppDialog({
  open,
  onOpenChange,
  workspaceSlug,
  slug,
  displayName,
  onDeleted,
}: Props) {
  const [confirmText, setConfirmText] = useState("");

  // Reset the confirm input every time the dialog opens — otherwise a
  // stale value from a previous open would let the user one-click delete.
  useEffect(() => {
    if (open) setConfirmText("");
  }, [open]);

  const canDelete = confirmText.trim() === slug;

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Delete ${displayName}?`}
      description={
        <>
          This moves <code className="font-mono">ACE/{slug}</code> to
          Google Drive's trash (recoverable for 30 days) and deletes any
          chat sessions linked to this opp. Cannot be undone from ace-web.
        </>
      }
      destructive
      confirmLabel="Delete opp"
      confirmingLabel="Deleting…"
      confirmDisabled={!canDelete}
      confirmDisabledTitle="Type the opp ID to enable delete"
      successToast={`Deleted ${displayName}`}
      errorToastPrefix="Delete failed"
      onConfirm={async () => {
        await deleteOpp(workspaceSlug, slug);
        onDeleted?.();
      }}
    >
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
          <code className="font-mono text-foreground">{slug}</code> to
          confirm:
        </label>
        <input
          id="confirm-delete-slug"
          type="text"
          autoComplete="off"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder={slug}
          className="rounded border border-input bg-card px-2 py-1 text-sm font-mono text-foreground focus:border-ring focus:outline-none"
        />
      </div>
    </ConfirmDialog>
  );
}
