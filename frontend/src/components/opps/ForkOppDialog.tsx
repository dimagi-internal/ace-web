import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, GitFork, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { forkOpp } from "@/api/opps";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// After this many ms of "Forking…", show a "still copying" hint so the
// user knows the dialog hasn't frozen on a large-opp Drive copy.
const SLOW_AFTER_MS = 10_000;
// last_actor_at within this many minutes = "opp may still be running".
// We don't block the fork; just warn so the user doesn't accidentally
// fork a half-baked state.
const RECENT_ACTIVITY_MIN = 10;

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Source opp slug to fork from. */
  sourceSlug: string;
  /** Phase NAME (e.g. ``design-review``) the fork resumes from. */
  forkAtPhase: string;
  /** Human label for the phase (e.g. ``Design Review``). Used in copy. */
  forkAtPhaseDisplay: string;
  /**
   * ISO-8601 timestamp of the source run's last actor activity (from
   * state.yaml). When within the last RECENT_ACTIVITY_MIN minutes, the
   * dialog surfaces a warning that the opp may still be running.
   */
  sourceLastActorAt?: string | null;
}

/**
 * Confirm + fork dialog. Recursively copies the source opp's Drive folder
 * to a new slug and resets ``state.yaml.current_phase`` to the fork target
 * so the next ``/ace:run`` resumes from there.
 *
 * Default slug: ``<source>-fork-YYYYMMDD-HHMM``. Editable. Slug-format
 * validation matches backend (``[a-z0-9][a-z0-9-]{0,62}[a-z0-9]``).
 *
 * Synchronous Drive copy can take 30-60s on large opps; the dialog stays
 * open with a "forking…" state until the API resolves.
 */
export function ForkOppDialog({
  open,
  onOpenChange,
  sourceSlug,
  forkAtPhase,
  forkAtPhaseDisplay,
  sourceLastActorAt,
}: Props) {
  const [slug, setSlug] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [slow, setSlow] = useState(false);
  const navigate = useNavigate();
  const { workspaceSlug } = useParams<{ workspaceSlug?: string }>();

  // Compute a sensible default each time the dialog opens. Using an
  // effect (not useState initializer) so re-opening on a different opp
  // refreshes the default instead of stale-bleeding the prior slug.
  useEffect(() => {
    if (!open) return;
    setSlug(defaultForkSlug(sourceSlug));
    setSlow(false);
  }, [open, sourceSlug]);

  // Promote to "still copying…" after SLOW_AFTER_MS so the dialog
  // doesn't look frozen during a 30-60s Drive copy.
  useEffect(() => {
    if (!submitting) return;
    const t = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(t);
  }, [submitting]);

  const validSlug = SLUG_RE.test(slug) && slug !== sourceSlug;
  const recentlyActive = isRecentlyActive(sourceLastActorAt);

  async function handleFork() {
    if (!validSlug) return;
    setSubmitting(true);
    try {
      const result = await forkOpp(sourceSlug, {
        new_slug: slug,
        fork_at_phase: forkAtPhase,
      });
      toast.success(`Forked to ${result.slug}`);
      onOpenChange(false);
      const dest = workspaceSlug
        ? `/w/${workspaceSlug}/opps/${result.slug}`
        : `/opps/${result.slug}`;
      navigate(dest);
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
            Fork from {forkAtPhaseDisplay}
          </DialogTitle>
          <DialogDescription>
            Creates a new opp by copying{" "}
            <code className="font-mono">ACE/{sourceSlug}</code> and resetting
            its plan to start at{" "}
            <code className="font-mono">{forkAtPhase}</code>. Artifacts from
            phases past <code className="font-mono">{forkAtPhase}</code> are
            kept in the copy but will be overwritten when the next{" "}
            <code className="font-mono">/ace:run</code> picks up.
            {" "}<strong>The Drive copy is recursive and may take 30–60 seconds.</strong>
          </DialogDescription>
        </DialogHeader>
        {recentlyActive && !submitting && (
          <div
            className="flex items-start gap-2 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
            role="alert"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              The source opp had activity in the last {RECENT_ACTIVITY_MIN} minutes —
              forking now copies a possibly-mid-flight state. If a run is
              actively in progress, wait for it to settle first.
            </span>
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="fork-new-slug"
            className="text-xs text-muted-foreground"
          >
            New opp ID
          </label>
          <input
            id="fork-new-slug"
            type="text"
            autoComplete="off"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            disabled={submitting}
            className="rounded border border-input bg-card px-2 py-1 text-sm font-mono text-foreground focus:border-ring focus:outline-none"
          />
          {slug && !validSlug && (
            <p className="text-[10px] text-destructive">
              {slug === sourceSlug
                ? "Must differ from the source opp ID."
                : "ID must be lowercase letters, digits, and hyphens (3–64 chars)."}
            </p>
          )}
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
            onClick={handleFork}
            disabled={submitting || !validSlug}
          >
            {submitting ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                {slow ? "Still copying…" : "Forking…"}
              </>
            ) : (
              "Fork"
            )}
          </Button>
        </DialogFooter>
        {submitting && slow && (
          <p className="-mt-2 text-[11px] text-muted-foreground">
            Drive recursive copy in progress. Large opps can take up to a
            minute. Don't close this tab.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}

function isRecentlyActive(iso: string | null | undefined): boolean {
  if (!iso) return false;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return false;
  return Date.now() - t < RECENT_ACTIVITY_MIN * 60 * 1000;
}

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$/;

function defaultForkSlug(sourceSlug: string): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp =
    now.getFullYear() +
    pad(now.getMonth() + 1) +
    pad(now.getDate()) +
    "-" +
    pad(now.getHours()) +
    pad(now.getMinutes());
  // Trim source slug if combining would exceed 64 chars; "-fork-" + stamp
  // is 16 chars, so the trim point is 64 - 16 = 48.
  const trimmed = sourceSlug.length > 48 ? sourceSlug.slice(0, 48) : sourceSlug;
  return `${trimmed}-fork-${stamp}`;
}
