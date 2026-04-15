import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { RunSummary } from "@/api/types";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  slug: string;
  runs: RunSummary[];
}

export function CompareRunsDialog({ open, onOpenChange, slug, runs }: Props) {
  const navigate = useNavigate();
  const [fromRun, setFromRun] = useState("");
  const [toRun, setToRun] = useState("");

  // Initialize defaults when opening (or when runs change).
  useEffect(() => {
    if (open && runs.length > 0) {
      setFromRun(runs[1]?.run_id ?? runs[0].run_id);
      setToRun(runs[0].run_id);
    }
  }, [open, runs]);

  function go() {
    navigate(`/opps/${slug}/compare?from=${fromRun}&to=${toRun}`);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Compare runs</DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-4">
          <label className="flex flex-col gap-1 text-sm">
            From
            <select
              value={fromRun}
              onChange={(e) => setFromRun(e.target.value)}
              className="rounded border border-border bg-card p-2"
            >
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            To
            <select
              value={toRun}
              onChange={(e) => setToRun(e.target.value)}
              className="rounded border border-border bg-card p-2"
            >
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={go} disabled={!fromRun || !toRun || fromRun === toRun}>
            Compare
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
