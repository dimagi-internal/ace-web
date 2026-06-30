import { type ReactNode, useState } from "react";
import { toast } from "sonner";

import { Button } from "@marshellis/canopy-ui/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Heading text shown at the top of the dialog. */
  title: ReactNode;
  /** Body shown beneath the title in muted style. Supply children instead
   * for richer body content (form fields, type-to-confirm, etc). */
  description?: ReactNode;
  /** Optional richer body. Renders BELOW the description. */
  children?: ReactNode;
  /** Default: "Confirm". Used when confirming is false. */
  confirmLabel?: string;
  /** Default: "${confirmLabel}…". Used while onConfirm is in flight. */
  confirmingLabel?: string;
  /** Default: "Cancel". */
  cancelLabel?: string;
  /** Renders the confirm button in the destructive variant. Default false. */
  destructive?: boolean;
  /** Disables the confirm button (e.g. when a type-to-confirm gate
   * isn't yet satisfied). Submitting always disables it regardless. */
  confirmDisabled?: boolean;
  /** Tooltip on the confirm button while disabled (e.g. "Type the opp
   * ID to enable delete"). */
  confirmDisabledTitle?: string;
  /** Async confirm handler. The dialog manages the submitting state and
   * closes itself on success. Errors are caught and surfaced via toast;
   * callers don't need their own try/catch unless they want richer
   * messaging. */
  onConfirm: () => Promise<void>;
  /** Toast text on success. Default: no toast (caller handles). */
  successToast?: string;
  /** Format for the error toast. Default: ``"${verb} failed: ${err}"`` —
   * the verb is the confirmLabel, lowercased and stripped of the leading
   * "delete"/"trash" cue if present. Pass an explicit string to override. */
  errorToastPrefix?: string;
}

/**
 * Generic confirm/cancel dialog used by DeleteOppDialog, DeleteRunDialog,
 * and other destructive single-action surfaces. Encapsulates:
 *
 * - Dialog shell + Cancel / Confirm footer button pair
 * - Submitting state (button label flip + both buttons disabled)
 * - Async error → toast translation so callers' onConfirm can simply
 *   ``throw`` or ``await deleteFoo()`` without a try/catch
 *
 * Form-shape dialogs (NewOppDialog, ForkOppDialog, EditArtifactDialog)
 * stay bespoke — their layouts diverge enough that consolidating would
 * pay off less than this extraction does for the destructive pair.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  confirmLabel = "Confirm",
  confirmingLabel,
  cancelLabel = "Cancel",
  destructive = false,
  confirmDisabled = false,
  confirmDisabledTitle,
  onConfirm,
  successToast,
  errorToastPrefix,
}: ConfirmDialogProps) {
  const [submitting, setSubmitting] = useState(false);

  async function handleConfirm() {
    if (submitting || confirmDisabled) return;
    setSubmitting(true);
    try {
      await onConfirm();
      if (successToast) toast.success(successToast);
      onOpenChange(false);
    } catch (e) {
      const prefix = errorToastPrefix ?? `${confirmLabel} failed`;
      toast.error(`${prefix}: ${String((e as Error).message ?? e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {children}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? "destructive" : "default"}
            onClick={handleConfirm}
            disabled={submitting || confirmDisabled}
            title={
              !submitting && confirmDisabled ? confirmDisabledTitle : undefined
            }
          >
            {submitting ? (confirmingLabel ?? `${confirmLabel}…`) : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
