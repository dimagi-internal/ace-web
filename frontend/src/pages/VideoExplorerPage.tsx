import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ChevronLeft,
  Copy,
  Loader2,
  RefreshCw,
  Save,
} from "lucide-react";

import {
  copyRun,
  getRenderStatus,
  getVideoProgram,
  getVideoRun,
  triggerBuild,
  type RenderStatus,
  type RunDetail,
  type VideoProgramDetail,
} from "@/api/videos";
import { BeatEditor } from "@/components/videos/BeatEditor";
import { useFeatures } from "@/lib/features";

const POLL_INTERVAL_MS = 4000;

export default function VideoExplorerPage() {
  const navigate = useNavigate();
  const params = useParams<{
    workspaceSlug: string;
    programSlug: string;
    runId?: string;
  }>();
  const { workspaceSlug, programSlug, runId } = params;

  const [program, setProgram] = useState<VideoProgramDetail | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<RenderStatus | null>(null);
  const [busyAction, setBusyAction] = useState<"render" | "save" | "copy" | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const wasBusyRef = useRef(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // Feature flag — gates the new React BeatEditor below. Returns null while
  // loading, in which case we fall through to the iframe path (the safe
  // default). See frontend/src/lib/features.ts.
  const features = useFeatures();
  const useReactBeatEditor = Boolean(features?.ACE_VIDEO_BEAT_EDITOR_REACT);

  // Resolve which run to view: explicit runId in URL, else the program's latest.
  const resolvedRunId = useMemo(() => {
    if (runId) return runId;
    if (program?.runs?.length) return program.runs[program.runs.length - 1].run_id;
    return null;
  }, [runId, program]);

  // Load the program (always; surfaces runs list for the picker).
  useEffect(() => {
    if (!workspaceSlug || !programSlug) return;
    let cancelled = false;
    getVideoProgram(workspaceSlug, programSlug)
      .then((data) => {
        if (!cancelled) setProgram(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, programSlug]);

  // Load the active run.
  useEffect(() => {
    if (!workspaceSlug || !programSlug || !resolvedRunId) {
      setRun(null);
      return;
    }
    let cancelled = false;
    getVideoRun(workspaceSlug, programSlug, resolvedRunId)
      .then((data) => {
        if (!cancelled) setRun(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, programSlug, resolvedRunId]);

  // Poll render status while busy + auto-refresh iframe on trailing edge.
  useEffect(() => {
    if (!workspaceSlug || !programSlug || !resolvedRunId) return;
    let cancelled = false;

    async function tick() {
      if (cancelled) return;
      try {
        const next = await getRenderStatus(workspaceSlug!, programSlug!, resolvedRunId!);
        if (cancelled) return;
        if (wasBusyRef.current && !next.busy && iframeRef.current) {
          iframeRef.current.src = iframeRef.current.src;
        }
        wasBusyRef.current = next.busy;
        setStatus(next);
      } catch {
        /* swallow */
      }
    }

    tick();
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [workspaceSlug, programSlug, resolvedRunId]);

  async function handleRender() {
    if (!workspaceSlug || !programSlug || !resolvedRunId) return;
    // Commit any in-progress edits before kicking off the render so
    // partial textbox content isn't silently lost.
    await flushPendingEdits();
    setBusyAction("render");
    setActionMsg(null);
    try {
      const r = await triggerBuild(workspaceSlug, programSlug, resolvedRunId, "render");
      setActionMsg(r.message);
      if (r.triggered) {
        wasBusyRef.current = true;
        setStatus({
          program_slug: programSlug,
          run_id: resolvedRunId,
          busy: true,
          started_at: new Date().toISOString(),
        });
      }
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyAction(null);
    }
  }

  type SaveAllResult = { saved: number; skipped: number; failed: number };
  async function flushPendingEdits(): Promise<SaveAllResult> {
    const fn = (iframeRef.current?.contentWindow as
      | (Window & { saveAllPending?: () => Promise<SaveAllResult> })
      | null
    )?.saveAllPending;
    if (typeof fn !== "function") return { saved: 0, skipped: 0, failed: 0 };
    try {
      return await fn();
    } catch {
      return { saved: 0, skipped: 0, failed: 1 };
    }
  }

  async function handleSave() {
    setBusyAction("save");
    setActionMsg(null);
    const r = await flushPendingEdits();
    if (r.failed > 0) {
      setActionMsg(`Save failed for ${r.failed} edit${r.failed === 1 ? "" : "s"}`);
    } else if (r.saved > 0) {
      setActionMsg(`Saved ${r.saved} edit${r.saved === 1 ? "" : "s"} · click Re-render to regenerate`);
    } else {
      setActionMsg("No pending edits to save");
    }
    setBusyAction(null);
  }

  async function handleCopyRun() {
    if (!workspaceSlug || !programSlug) return;
    setBusyAction("copy");
    setActionMsg(null);
    try {
      const r = await copyRun(workspaceSlug, programSlug);
      setActionMsg(`Copied ${r.copied_from} → ${r.new_run_id}`);
      // Reload program (runs list refreshes) and navigate to the new run.
      const next = await getVideoProgram(workspaceSlug, programSlug);
      setProgram(next);
      navigate(`/w/${workspaceSlug}/videos/${programSlug}/runs/${r.new_run_id}`);
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyAction(null);
    }
  }

  function handleRunPick(e: React.ChangeEvent<HTMLSelectElement>) {
    const r = e.target.value;
    if (workspaceSlug && programSlug && r) {
      navigate(`/w/${workspaceSlug}/videos/${programSlug}/runs/${r}`);
    }
  }

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-card px-4 py-2">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            to={`/w/${workspaceSlug}/videos`}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            All programs
          </Link>
          <h1 className="text-sm font-medium">{run?.name ?? program?.name ?? programSlug}</h1>

          {program?.runs?.length ? (
            <div className="flex items-center gap-1.5">
              <label
                htmlFor="run-picker"
                className="text-[10px] uppercase tracking-wider text-muted-foreground"
              >
                Run
              </label>
              <select
                id="run-picker"
                value={resolvedRunId ?? ""}
                onChange={handleRunPick}
                className="rounded-md border border-border bg-card px-1.5 py-0.5 text-xs font-medium"
              >
                {program.runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id}
                    {r.has_output ? "" : "  (no render yet)"}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={handleCopyRun}
                title="Snapshot this run into a new run-NNN — both stay mutable."
                className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
              >
                <Copy className="h-3 w-3" />
                Copy
              </button>
            </div>
          ) : null}

          {run?.yaml_path && (
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {run.yaml_path}
            </code>
          )}
        </div>

        <div className="flex items-center gap-2">
          {actionMsg && !status?.busy && (
            <span className="text-xs text-muted-foreground">{actionMsg}</span>
          )}
          {status?.busy ? (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Re-render in progress
              {status.started_at && (
                <span className="text-muted-foreground/70">
                  · started {new Date(status.started_at).toLocaleTimeString()}
                </span>
              )}
            </div>
          ) : (
            <>
              <button
                type="button"
                disabled={busyAction !== null || !resolvedRunId}
                onClick={handleSave}
                title="Save every in-progress edit on this page to spec.yaml. Does not re-render."
                className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50"
              >
                <Save className="h-3 w-3" />
                {busyAction === "save" ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                disabled={busyAction !== null || !resolvedRunId}
                onClick={handleRender}
                title="Save any pending edits and regenerate output.mp4 — the one button that produces a new render."
                className="inline-flex items-center gap-1.5 rounded-md border border-primary bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground shadow-sm hover:opacity-90 disabled:opacity-50"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Re-render
              </button>
            </>
          )}
        </div>
      </header>

      {error ? (
        <div className="flex flex-1 items-center justify-center p-8">
          <div className="flex max-w-md items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
            <div>
              <div className="font-medium">Couldn't load explorer</div>
              <div className="text-muted-foreground">{error}</div>
            </div>
          </div>
        </div>
      ) : !run ? (
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Loading…
        </div>
      ) : useReactBeatEditor && run.spec && workspaceSlug && programSlug && resolvedRunId ? (
        <BeatEditor
          workspaceSlug={workspaceSlug}
          programSlug={programSlug}
          runId={resolvedRunId}
          spec={run.spec}
          onSpecRefetched={(s) => setRun((rd) => (rd ? { ...rd, spec: s } : rd))}
        />
      ) : (
        <iframe
          ref={iframeRef}
          src={
            (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") + run.explorer_url
          }
          title={`Clip explorer: ${run.name}`}
          className="flex-1 border-0"
          allow="fullscreen"
        />
      )}
    </div>
  );
}
