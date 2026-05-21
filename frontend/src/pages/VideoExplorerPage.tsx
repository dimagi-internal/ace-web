import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ChevronLeft,
  Copy,
  Loader2,
  MoreHorizontal,
  RefreshCw,
} from "lucide-react";

import {
  copyRun,
  getRenderLog,
  getRenderStatus,
  getVideoProgram,
  getVideoRun,
  triggerBuild,
  type RenderStatus,
  type RunDetail,
  type VideoProgramDetail,
} from "@/api/videos";
import { BeatEditor } from "@/components/videos/BeatEditor";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { relativeTime } from "@/lib/relativeTime";

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
  // Captured tail of render.log, set once when render-status transitions
  // to appears_failed=true. Drives the inline error banner under the
  // header. `null` while loading; "" if log empty / missing.
  const [renderErrorLog, setRenderErrorLog] = useState<string | null>(null);
  const wasBusyRef = useRef(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

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
        if (next.busy) {
          // User kicked off a new render — drop the cached error so
          // the banner only ever shows the most recent failure.
          setRenderErrorLog(null);
        } else if (next.appears_failed) {
          // On the leading edge of appears_failed, pull render.log
          // once so we can surface the actual error to the user. Mac
          // development bumps this all the time (in-container render
          // hits esbuild platform-mismatch — see render_locally.py
          // module doc). Use a functional setter so we only fire the
          // fetch if the log isn't already cached, without needing
          // renderErrorLog in the effect deps (which would restart
          // the polling loop).
          setRenderErrorLog((prev) => {
            if (prev !== null) return prev;
            // Async fetch is intentionally unawaited inside this
            // setter — we just need to know "no fetch in flight yet";
            // empty string acts as the placeholder.
            getRenderLog(workspaceSlug!, programSlug!, resolvedRunId!)
              .then((r) => {
                if (!cancelled) setRenderErrorLog(r.log ?? "");
              })
              .catch(() => {
                if (!cancelled) setRenderErrorLog("");
              });
            return "";
          });
        }
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
      {/* Compact run summary header (variant B from the prototype sandbox).
          The previous header carried a colored beat-strip + dot legend
          (TimelineStrip) plus the spec.yaml path + Copy run button —
          three competing visualisations on a page where the BeatList
          below already lists every beat. Now: just identity +
          actions, with a single one-line stat (beats · duration ·
          render status · voice · resolution) that tells you the
          things you actually want to know at a glance. spec.yaml path
          and Copy run live behind a kebab menu — they're rarely-used
          power-user affordances, not header chrome. */}
      <header className="flex flex-col gap-1 border-b border-border bg-card px-4 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
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
              <select
                id="run-picker"
                value={resolvedRunId ?? ""}
                onChange={handleRunPick}
                className="rounded-md border border-border bg-card px-1.5 py-0.5 text-xs font-medium"
                aria-label="Run"
              >
                {program.runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id}
                    {r.has_output ? "" : "  (no render yet)"}
                  </option>
                ))}
              </select>
            ) : null}
          </div>

          <div className="flex items-center gap-1.5">
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
              // Save lives in the BeatEditor's sticky TopBar — only that
              // button is wired to the React buffer + POST /edit-batch.
              <button
                type="button"
                disabled={busyAction !== null || !resolvedRunId}
                onClick={handleRender}
                title="Regenerate output.mp4 from the current spec.yaml — the one button that produces a new render."
                className="inline-flex items-center gap-1.5 rounded-md border border-primary bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground shadow-sm hover:opacity-90 disabled:opacity-50"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Re-render
              </button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger
                aria-label="More actions"
                title="More actions"
                className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <MoreHorizontal className="h-4 w-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuItem
                  onClick={handleCopyRun}
                  disabled={busyAction !== null || !resolvedRunId}
                >
                  <Copy className="h-3.5 w-3.5" />
                  Copy run
                </DropdownMenuItem>
                {run?.yaml_path && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={() => {
                        if (run.yaml_path) navigator.clipboard?.writeText(run.yaml_path).catch(() => {});
                      }}
                      title={`Copy ${run.yaml_path} to clipboard`}
                    >
                      <span className="truncate font-mono text-[10px] text-muted-foreground">
                        {run.yaml_path}
                      </span>
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        <RunSummaryLine run={run} />
      </header>

      {status?.appears_failed && (
        <RenderErrorBanner
          log={renderErrorLog}
          programSlug={programSlug ?? ""}
          startedAt={status.started_at}
        />
      )}

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
      ) : run.spec && workspaceSlug && programSlug && resolvedRunId ? (
        // The page is locked at h-[calc(100vh-3rem)] so the inner editor
        // must own its own vertical scroll — otherwise BeatList overflow
        // gets clipped at the page bottom. The iframe path used flex-1
        // for the same reason; React tree needs an overflow-y-auto wrapper.
        <div className="flex-1 overflow-y-auto px-4 py-4">
          <BeatEditor
            key={`${workspaceSlug}-${programSlug}-${resolvedRunId}`}
            workspaceSlug={workspaceSlug}
            programSlug={programSlug}
            runId={resolvedRunId}
            spec={run.spec}
            onSpecRefetched={(s) => setRun((rd) => (rd ? { ...rd, spec: s } : rd))}
            onRerender={handleRender}
          />
        </div>
      ) : (
        // Fallback only when the run pre-dates the parsed-spec endpoint
        // (no `spec` field on the response). Renders the legacy clip
        // explorer iframe so the run isn't unusable.
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

// One-line run summary rendered under the breadcrumb. Pure presentational:
// pulls beats / voice / dimensions out of the parsed spec and renders a
// dot-separated row. Renders nothing while the run is still loading so the
// header doesn't reflow once the data arrives.
function RunSummaryLine({ run }: { run: RunDetail | null }) {
  if (!run) return null;
  const beats = run.spec?.beats ?? [];
  const total = beats.reduce((s: number, b) => s + (b.seconds ?? 0), 0);
  const voice =
    (run.spec?.voice as { provider?: string } | undefined)?.provider ?? null;
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
      <span>{beats.length} beats</span>
      <span aria-hidden>·</span>
      <span>{total.toFixed(1)}s total</span>
      <span aria-hidden>·</span>
      {(() => {
        // Three states for the render-freshness chip:
        //   - no render yet                 (amber)
        //   - rendered Nm ago               (emerald)
        //   - rendered Nm ago · stale       (amber, when spec.yaml in
        //                                    Drive is newer than final.mp4 —
        //                                    the user has saved edits that
        //                                    haven't been re-rendered yet).
        // Stale beats the green state so a user mid-edit never sees the
        // green "all good" badge while their saves still aren't in the
        // embedded player.
        const isStale =
          run.has_output &&
          run.output_rendered_at !== null &&
          run.spec_modified_at !== null &&
          new Date(run.spec_modified_at).getTime() >
            new Date(run.output_rendered_at).getTime();
        const colorClass =
          run.has_output && !isStale
            ? "text-emerald-700 dark:text-emerald-500"
            : "text-amber-700 dark:text-amber-500";
        const titleAttr = [
          run.output_rendered_at ? `final.mp4: ${run.output_rendered_at}` : null,
          run.spec_modified_at ? `spec.yaml: ${run.spec_modified_at}` : null,
        ]
          .filter(Boolean)
          .join("\n");
        const label = !run.has_output
          ? "no render yet"
          : run.output_rendered_at
            ? isStale
              ? `rendered ${relativeTime(run.output_rendered_at)} · stale (edited since)`
              : `rendered ${relativeTime(run.output_rendered_at)}`
            : "rendered";
        return (
          <span className={colorClass} title={titleAttr || undefined}>
            {label}
          </span>
        );
      })()}
      {voice && (
        <>
          <span aria-hidden>·</span>
          <span>voice: {voice}</span>
        </>
      )}
      <span aria-hidden>·</span>
      <span>1280×720</span>
    </div>
  );
}

// Inline error banner shown when the in-container render fails. The
// most common case in dev — by a wide margin — is the Mac/Docker
// esbuild platform mismatch: the host installed `@esbuild/darwin-arm64`
// into node_modules, but the Django container is `@esbuild/linux-arm64`,
// and the tsx runner can't find a binary it can exec. We detect that
// signature explicitly and surface the known recovery path
// (scripts/render_locally.py). All other failures fall through to a
// generic banner with the last 12 lines of render.log so the user has
// something to work with.
function RenderErrorBanner({
  log,
  programSlug,
  startedAt,
}: {
  log: string | null;
  programSlug: string;
  startedAt: string | null;
}) {
  // Mac signature: esbuild prints a multi-line explainer that always
  // contains this exact substring when @esbuild/<platform> is wrong.
  const isMacEsbuildFailure =
    log !== null && log.includes("@esbuild/darwin-arm64");
  const tail = (log ?? "")
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .slice(-12)
    .join("\n");
  return (
    <div className="border-b border-amber-700/30 bg-amber-950/5 px-4 py-3 text-sm">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600" />
        <div className="min-w-0 flex-1">
          <div className="mb-1 font-medium text-amber-700 dark:text-amber-500">
            Render failed
            {startedAt && (
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                · started {new Date(startedAt).toLocaleTimeString()}
              </span>
            )}
          </div>
          {log === null ? (
            <div className="text-xs text-muted-foreground">Loading render log…</div>
          ) : isMacEsbuildFailure ? (
            <>
              <p className="text-xs text-muted-foreground">
                In-container render hit the macOS/Linux esbuild mismatch —
                a known dev-only failure (the host's node_modules has
                <code className="mx-1 rounded bg-muted px-1 font-mono text-[10px]">
                  @esbuild/darwin-arm64
                </code>
                but the Django container needs the linux build). Run the
                render on Mac metal instead:
              </p>
              <pre className="mt-1.5 overflow-x-auto rounded bg-muted/40 px-2 py-1.5 font-mono text-[11px]">
                uv run --extra walkthrough python scripts/render_locally.py {programSlug}
              </pre>
            </>
          ) : tail ? (
            <details className="text-xs">
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                Show last 12 lines of render.log
              </summary>
              <pre className="mt-1.5 max-h-48 overflow-auto rounded bg-muted/40 px-2 py-1.5 font-mono text-[10px] leading-tight">
                {tail}
              </pre>
            </details>
          ) : (
            <div className="text-xs text-muted-foreground">
              No render log available. The container may have died before
              writing output.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
