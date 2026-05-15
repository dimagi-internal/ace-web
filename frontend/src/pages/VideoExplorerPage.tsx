import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ChevronLeft, Hammer, Loader2, RefreshCw } from "lucide-react";

import {
  getRenderStatus,
  getVideoProgram,
  triggerBuild,
  type RenderStatus,
  type VideoProgramDetail,
} from "@/api/videos";

const POLL_INTERVAL_MS = 4000;

export default function VideoExplorerPage() {
  const { workspaceSlug, programSlug } = useParams<{
    workspaceSlug: string;
    programSlug: string;
  }>();
  const [detail, setDetail] = useState<VideoProgramDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<RenderStatus | null>(null);
  const [buildMsg, setBuildMsg] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<"render" | "build-only" | null>(null);
  const wasBusyRef = useRef(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  useEffect(() => {
    if (!workspaceSlug || !programSlug) return;
    let cancelled = false;
    getVideoProgram(workspaceSlug, programSlug)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, programSlug]);

  // Poll render status while busy so the UI surfaces in-flight renders.
  useEffect(() => {
    if (!workspaceSlug || !programSlug) return;
    let cancelled = false;

    async function tick() {
      if (cancelled) return;
      try {
        const next = await getRenderStatus(workspaceSlug!, programSlug!);
        if (!cancelled) {
          // Auto-refresh the iframe once a render finishes — the
          // generated HTML (and the embedded final.mp4) will have been
          // rewritten while it was running, so the operator wants to
          // see the new output immediately. Compare against the prior
          // busy state to fire exactly once on the trailing edge.
          if (wasBusyRef.current && !next.busy && iframeRef.current) {
            iframeRef.current.src = iframeRef.current.src;
          }
          wasBusyRef.current = next.busy;
          setStatus(next);
        }
      } catch {
        /* swallow — UI just won't surface status this tick */
      }
    }

    tick();
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [workspaceSlug, programSlug]);

  async function handleBuild(mode: "render" | "build-only") {
    if (!workspaceSlug || !programSlug) return;
    setBusyAction(mode);
    setBuildMsg(null);
    try {
      const r = await triggerBuild(workspaceSlug, programSlug, mode);
      setBuildMsg(r.message);
      // Optimistically mark busy so the spinner shows up before the
      // next poll tick lands.
      if (r.triggered) {
        wasBusyRef.current = true;
        setStatus({
          program_slug: programSlug,
          busy: true,
          started_at: new Date().toISOString(),
        });
      }
    } catch (e) {
      setBuildMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col">
      <header className="flex items-center justify-between border-b border-border bg-card px-4 py-2">
        <div className="flex items-center gap-3">
          <Link
            to={`/w/${workspaceSlug}/videos`}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            All programs
          </Link>
          <h1 className="text-sm font-medium">
            {detail?.name ?? programSlug}
          </h1>
          {detail?.yaml_path && (
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {detail.yaml_path}
            </code>
          )}
        </div>
        <div className="flex items-center gap-2">
          {buildMsg && !status?.busy && (
            <span className="text-xs text-muted-foreground">{buildMsg}</span>
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
                disabled={busyAction !== null}
                onClick={() => handleBuild("build-only")}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                title="Regenerate the explorer HTML against the current YAML — fast, no re-render."
              >
                <Hammer className="h-3 w-3" />
                Rebuild HTML
              </button>
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() => handleBuild("render")}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                title="Run npm run render — produces a fresh draft MP4, then rebuilds the explorer."
              >
                <RefreshCw className="h-3 w-3" />
                Render draft
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
      ) : !detail ? (
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Loading…
        </div>
      ) : (
        <iframe
          ref={iframeRef}
          // The explorer HTML is generated by `npm run build-clip-explorer`
          // and served (with URL rewrites + CSRF wrapper + dark-theme
          // injection) by the Django app. We embed it here so it
          // inherits ace-web's chrome and auth. Same-origin so cookies +
          // workspace gating apply.
          // Backend returns a bare /api/... path; we prefix BASE_URL so
          // the iframe's relative fetches (library.json, edit, feedback)
          // resolve under the SPA's URL prefix (/ace/ in prod-parity dev,
          // / when FORCE_SCRIPT_NAME='').
          src={
            (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "") +
            detail.explorer_url
          }
          title={`Clip explorer: ${detail.name}`}
          className="flex-1 border-0"
          allow="fullscreen"
        />
      )}
    </div>
  );
}
