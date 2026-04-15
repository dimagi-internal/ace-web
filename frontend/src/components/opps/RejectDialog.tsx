import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  skill: string;
  onOpenChange: (v: boolean) => void;
  onConfirm: (reason: string) => Promise<void>;
}

export function RejectDialog({ open, skill, onOpenChange, onConfirm }: Props) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function handle() {
    setBusy(true);
    try {
      await onConfirm(reason);
      setReason("");
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Reject {skill} gate</DialogTitle>
        </DialogHeader>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={4}
          placeholder="Reason for rejecting…"
          className="w-full rounded border border-border bg-card p-2 text-xs"
        />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="destructive" onClick={handle} disabled={!reason.trim() || busy}>
            Reject
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
