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
      toast.success(actionSuccessMessage(action), {
        description: "ACE picks it up in the working chat — see the right pane for the response.",
      });
    } catch (e) {
      toast.error(`${humanizeAction(action)} failed`, {
        description: (e as Error).message,
      });
    } finally {
      setBusy(false);
    }
  }

  function humanizeAction(a: string): string {
    if (a === "approve") return "Approve gate";
    if (a === "reject") return "Reject gate";
    if (a === "rerun") return "Rerun";
    if (a === "run") return "Run";
    return a;
  }

  function actionSuccessMessage(a: string): string {
    if (a === "approve") return "Gate approved";
    if (a === "reject") return "Gate rejected";
    if (a === "rerun") return "Rerun queued";
    if (a === "run") return "Run queued";
    return `${humanizeAction(a)} sent`;
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
