import { useState } from "react";
import { toast } from "sonner";

import { runAction } from "@/api/opps";
import { Button } from "@/components/ui/button";
import { RejectDialog } from "./RejectDialog";

interface Props {
  slug: string;
  runId: string;
  skillName: string;
  status: string;
}

export function ActionButtons({ slug, runId, skillName, status }: Props) {
  const [busy, setBusy] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);

  async function call(action: string, payload: { reason?: string } = {}) {
    setBusy(true);
    try {
      await runAction(slug, runId, action, { skill: skillName, ...payload });
      toast.success(`${action} → chat`);
    } catch (e) {
      toast.error(`${action} failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const showRun = status === "pending";
  const showRerun = status === "complete" || status === "error" || status === "judge-fail";
  const showGate = status === "gate-pending";

  if (!showRun && !showRerun && !showGate) return null;

  return (
    <div className="flex flex-wrap gap-2">
      {showRun && <Button size="sm" disabled={busy} onClick={() => call("run")}>Run</Button>}
      {showRerun && <Button size="sm" variant="outline" disabled={busy} onClick={() => call("rerun")}>Rerun</Button>}
      {showGate && (
        <>
          <Button size="sm" disabled={busy} onClick={() => call("approve")}>Approve gate</Button>
          <Button size="sm" variant="destructive" disabled={busy} onClick={() => setRejectOpen(true)}>
            Reject gate
          </Button>
        </>
      )}
      <RejectDialog
        open={rejectOpen} skill={skillName} onOpenChange={setRejectOpen}
        onConfirm={(reason) => call("reject", { reason })}
      />
    </div>
  );
}
