import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { forkOpp, type ForkOppBody } from "@/api/opps";
import type { PhaseInfo } from "@/api/types.ws";
import type { EditOp } from "./decisionsReducer";

interface Props {
  open: boolean;
  onClose: () => void;
  workspaceSlug: string;
  sourceSlug: string;
  sourceRunId: string;
  initialForkAtPhase: string;
  phases: readonly PhaseInfo[];
  edits: readonly EditOp[];
  affectedDocs: readonly string[];
  /** Test seam: replace the forkOpp client call. */
  __forkOppForTest?: typeof forkOpp;
}

/**
 * Modal shown when the user confirms "Fork & re-run" with buffered
 * decision edits. Lists the artifacts the forked run will regenerate
 * (derived from the manifest crosswalk) and lets the user pick the fork
 * point if the auto-default isn't what they want.
 */
export function ForkWithEditsDialog({
  open,
  onClose,
  workspaceSlug,
  sourceSlug,
  sourceRunId,
  initialForkAtPhase,
  phases,
  edits,
  affectedDocs,
  __forkOppForTest,
}: Props) {
  const [forkAtPhase, setForkAtPhase] = useState(initialForkAtPhase);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  // Escape closes the modal (web/macOS convention). Skip while submitting
  // — closing mid-flight would orphan the in-flight fork.
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, submitting, onClose]);

  if (!open) return null;

  const onSubmit = async () => {
    setSubmitting(true);
    setError(null);
    const body: ForkOppBody = {
      fork_at_phase: forkAtPhase,
      source_run_id: sourceRunId,
      edits: edits.map((e) => ({ row_id: e.row_id, new_answer: e.new_answer })),
    };
    try {
      const fn = __forkOppForTest ?? forkOpp;
      const result = await fn(workspaceSlug, sourceSlug, body);
      navigate(`/w/${workspaceSlug}/opps/${result.slug}?run_id=${result.run_id}`);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-5 shadow-xl">
        <h2 className="text-base font-semibold text-foreground">
          Fork run with {edits.length} answer change{edits.length === 1 ? "" : "s"}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Your edits touch <code className="rounded bg-muted/40 px-1">{forkAtPhase}</code>.
          The new run will re-run from there and regenerate:
        </p>

        <ul className="mt-3 space-y-1 text-xs">
          {affectedDocs.length === 0 && (
            <li className="italic text-muted-foreground">
              The new run will regenerate this phase's outputs.
            </li>
          )}
          {affectedDocs.map((path) => (
            <li key={path} className="font-mono text-foreground">
              <span aria-hidden="true">• </span>
              <span>{path}</span>
            </li>
          ))}
        </ul>

        <label className="mt-4 block text-xs">
          <span className="text-muted-foreground">Fork point</span>
          <select
            value={forkAtPhase}
            onChange={(e) => setForkAtPhase(e.target.value)}
            className="mt-1 block w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
          >
            {phases.map((p) => (
              <option key={p.name} value={p.name}>
                {p.ordinal}. {p.display_name || p.name}
              </option>
            ))}
          </select>
        </label>

        {error && (
          <div className="mt-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md border border-border bg-background px-3 py-1.5 text-xs hover:bg-accent disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={submitting}
            className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            {submitting ? "Forking…" : "Fork & re-run"}
          </button>
        </div>
      </div>
    </div>
  );
}
