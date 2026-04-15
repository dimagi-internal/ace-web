import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { forkRun } from "@/api/opps";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  slug: string;
  runId: string;
  skill: string;
}

export function ForkDialog({ open, onOpenChange, slug, runId, skill }: Props) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"with-feedback" | "empty">("with-feedback");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      const r = await forkRun(slug, runId, {
        from_skill: skill, mode,
        feedback: mode === "with-feedback" ? feedback : undefined,
      });
      toast.success(`Created ${r.new_run_id}`);
      navigate(`/opps/${slug}/runs/${r.new_run_id}`);
      onOpenChange(false);
    } catch (e) {
      toast.error(`Fork failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = !busy && (mode === "empty" || feedback.trim().length > 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Fork from {skill}</DialogTitle>
          <DialogDescription>
            Create a new run of <code className="font-mono">{slug}</code>, inheriting artifacts produced before this step.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              checked={mode === "with-feedback"}
              onChange={() => setMode("with-feedback")}
              className="mt-1"
            />
            <div>
              <div>With feedback</div>
              <div className="text-xs text-muted-foreground">
                Inherit upstream artifacts; rerun from this step with feedback applied.
              </div>
            </div>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              checked={mode === "empty"}
              onChange={() => setMode("empty")}
              className="mt-1"
            />
            <div>
              <div>Empty</div>
              <div className="text-xs text-muted-foreground">
                Inherit only idea.md; rerun from step 1.
              </div>
            </div>
          </label>
          {mode === "with-feedback" && (
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={4}
              placeholder="What should change about this step's output?"
              className="rounded border border-border bg-card p-2 text-xs"
            />
          )}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={!canSubmit}>{busy ? "Forking…" : "Fork"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
