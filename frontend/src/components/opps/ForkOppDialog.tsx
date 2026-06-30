import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, GitFork, Loader2 } from "lucide-react";
import { toast } from "sonner";

import {
  forkOpp,
  getForkStatus,
  type ForkMode,
  type ForkProgress,
} from "@/api/opps";
import { ApiError } from "@/api/client";
import { Button } from "canopy-ui/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "canopy-ui/ui";

// After this many ms of "Forking…", show a "still copying" hint so the
// user knows the dialog hasn't frozen on a Drive copy.
const SLOW_AFTER_MS = 10_000;
// last_actor_at within this many minutes = "opp may still be running".
// Warn so the user doesn't fork a half-baked state.
const RECENT_ACTIVITY_MIN = 10;
// How often the dialog polls /fork/status while the fork runs.
const POLL_INTERVAL_MS = 750;

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Source opp slug — fork mints a new run under THIS opp. */
  sourceSlug: string;
  /** Source run-id the fork seeds from. */
  sourceRunId: string;
  /** Phase NAME (e.g. ``commcare-setup``) the fork resumes from. */
  forkAtPhase: string;
  /** Human label for the phase. Used in copy. */
  forkAtPhaseDisplay: string;
  /**
   * ISO-8601 timestamp of the source run's last actor activity. When
   * within the last RECENT_ACTIVITY_MIN minutes, the dialog warns that
   * the run may still be in progress.
   */
  sourceLastActorAt?: string | null;
}

/**
 * Confirm + fork dialog. Per the ACE plugin's canonical fork contract,
 * forking creates a NEW RUN under the same opp — not a new opp. The
 * new run carries forward upstream phase artifacts and per-run docs;
 * per-opp resources (opp.yaml, inputs/, eval-calibration/, etc.) stay
 * shared.
 *
 * Synchronous Drive copy proportional to the kept phase count. The
 * dialog polls /fork/status for a live "Copied N of M" while it runs.
 */
export function ForkOppDialog({
  open,
  onOpenChange,
  sourceSlug,
  sourceRunId,
  forkAtPhase,
  forkAtPhaseDisplay,
  sourceLastActorAt,
}: Props) {
  const [submitting, setSubmitting] = useState(false);
  const [slow, setSlow] = useState(false);
  const [progress, setProgress] = useState<ForkProgress | null>(null);
  const [mode, setMode] = useState<ForkMode>("keep-all");
  const navigate = useNavigate();
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();

  useEffect(() => {
    if (!open) return;
    setSlow(false);
    setProgress(null);
    setMode("keep-all");
  }, [open, sourceSlug]);

  // Promote to "still copying…" after SLOW_AFTER_MS so the dialog
  // doesn't look frozen during a multi-second Drive copy.
  useEffect(() => {
    if (!submitting) return;
    const t = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(t);
  }, [submitting]);

  // Poll /fork/status while the synchronous POST is in flight so we
  // can surface "Copied N of M" + a progress bar. The POST is on a
  // separate connection, so the browser happily fires this in parallel.
  useEffect(() => {
    if (!submitting) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const p = await getForkStatus(workspaceSlug ?? "", sourceSlug, sourceRunId);
        if (!cancelled) setProgress(p);
      } catch {
        /* poll failures are non-fatal — keep trying */
      }
    };
    tick();
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [submitting, sourceSlug, sourceRunId]);

  const recentlyActive = isRecentlyActive(sourceLastActorAt);

  async function handleFork() {
    setSubmitting(true);
    try {
      const result = await forkOpp(workspaceSlug ?? "", sourceSlug, {
        fork_at_phase: forkAtPhase,
        source_run_id: sourceRunId || null,
        mode,
      });
      toast.success(`Forked to run ${result.run_id}`);
      onOpenChange(false);
      const encSlug = encodeURIComponent(result.slug);
      const base = workspaceSlug
        ? `/w/${workspaceSlug}/opps/${encSlug}`
        : `/opps/${encSlug}`;
      navigate(`${base}?run_id=${encodeURIComponent(result.run_id)}`);
    } catch (err) {
      const detail = err instanceof ApiError ? err.message : String(err);
      toast.error(`Fork failed: ${detail}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitFork className="h-4 w-4 text-primary" />
            Fork run from {forkAtPhaseDisplay}
          </DialogTitle>
          <DialogDescription>
            Mints a new run under{" "}
            <code className="font-mono">ACE/{sourceSlug}</code>, carrying
            forward only the upstream phases. The new run's plan starts
            at <code className="font-mono">{forkAtPhase}</code>; per-opp
            state (opp.yaml, inputs, calibration, open questions, Connect
            IDs) stays shared with the source.
          </DialogDescription>
        </DialogHeader>
        {recentlyActive && !submitting && (
          <div
            className="flex items-start gap-2 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
            role="alert"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              Source run had activity in the last {RECENT_ACTIVITY_MIN} minutes —
              forking now snapshots a possibly-mid-flight state. If a run is
              actively in progress, wait for it to settle first.
            </span>
          </div>
        )}
        <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1 text-xs">
          <span className="text-muted-foreground">Source run</span>
          <code className="font-mono text-foreground">{sourceRunId || "(latest)"}</code>
          <span className="text-muted-foreground">Resume at</span>
          <code className="font-mono text-foreground">{forkAtPhase}</code>
        </div>
        <fieldset className="flex flex-col gap-2 text-xs" disabled={submitting}>
          <legend className="text-muted-foreground">Decisions</legend>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="fork-mode"
              checked={mode === "keep-all"}
              onChange={() => setMode("keep-all")}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium text-foreground">Keep all decisions</span>
              <span className="block text-muted-foreground">
                Every upstream decision carries forward — both AI defaults and your overrides.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="fork-mode"
              checked={mode === "keep-overrides-only"}
              onChange={() => setMode("keep-overrides-only")}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium text-foreground">Keep only my overrides</span>
              <span className="block text-muted-foreground">
                Only your explicit overrides carry forward; AI defaults are dropped so phases can re-derive them.
              </span>
            </span>
          </label>
        </fieldset>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button onClick={handleFork} disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Forking…
              </>
            ) : (
              "Fork run"
            )}
          </Button>
        </DialogFooter>
        {submitting && <ForkProgressView progress={progress} slow={slow} />}
      </DialogContent>
    </Dialog>
  );
}

function ForkProgressView({
  progress,
  slow,
}: {
  progress: ForkProgress | null;
  slow: boolean;
}) {
  const copied =
    progress && (progress.status === "copying" || progress.status === "done")
      ? progress.copied
      : 0;
  const total =
    progress && (progress.status === "copying" || progress.status === "done")
      ? progress.total
      : 0;
  const pct = total > 0 ? Math.min(100, Math.round((copied / total) * 100)) : 0;
  const current =
    progress && progress.status === "copying" ? progress.current : "";

  let label: string;
  if (!progress || progress.status === "unknown") {
    label = "Starting fork…";
  } else if (progress.status === "counting") {
    label = "Counting files in source run…";
  } else if (progress.status === "copying") {
    label = `Copying ${copied} of ${total} files`;
  } else if (progress.status === "finalizing") {
    label = "Finalizing fork…";
  } else if (progress.status === "done") {
    label = `Copied ${copied} of ${total} files. Opening run ${progress.new_run_id}…`;
  } else {
    label = "Working…";
  }

  return (
    <div className="-mt-1 flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{label}</span>
        {total > 0 && (
          <span className="font-mono tabular-nums">{pct}%</span>
        )}
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
        <div
          className={
            progress && progress.status === "copying" && total > 0
              ? "h-full bg-primary transition-[width] duration-300"
              : "h-full w-1/3 animate-pulse bg-primary/60"
          }
          style={
            progress && progress.status === "copying" && total > 0
              ? { width: `${pct}%` }
              : undefined
          }
        />
      </div>
      {current && (
        <p className="truncate font-mono text-[10px] text-muted-foreground">
          {current}
        </p>
      )}
      {slow && (
        <p className="text-[10px] text-muted-foreground">
          Drive copies are paced ~150 ms per file. Don't close this tab.
        </p>
      )}
    </div>
  );
}

function isRecentlyActive(iso: string | null | undefined): boolean {
  if (!iso) return false;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return false;
  return Date.now() - t < RECENT_ACTIVITY_MIN * 60 * 1000;
}
