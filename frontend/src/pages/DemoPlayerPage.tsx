/**
 * Demo Player — one saved run, presented to a room.
 *
 * Keyboard-first, because a presenter drives this without looking at the
 * screen they're pointing at: space plays and pauses, 1-4 pick an act,
 * arrows step the playhead, R restarts.
 *
 * Spec: docs/specs/2026-09-17-ace-demo-player-design.md
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  type DemoAct,
  type DemoActId,
  type DemoDecisions,
  type DemoGate,
  type DemoLedger,
  type DemoPayload,
  type DemoTimeline,
  fetchDemoPayload,
} from "@/api/demo";
import { DecisionsAct } from "@/components/demo/DecisionsAct";
import { GatesAct } from "@/components/demo/GatesAct";
import { LedgerAct } from "@/components/demo/LedgerAct";
import { TimelineAct } from "@/components/demo/TimelineAct";
import { usePlayback } from "@/components/demo/usePlayback";

/** How long the whole run takes to cross the screen. Three minutes is long
 *  enough to narrate over and short enough to hold a room. */
const DEFAULT_DEMO_SECONDS = 180;

export default function DemoPlayerPage() {
  const { workspaceSlug, slug, runId } = useParams<{
    workspaceSlug: string;
    slug: string;
    runId: string;
  }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "loaded"; payload: DemoPayload }
    | { kind: "error"; message: string }
  >({ kind: "loading" });

  const demoSeconds = Number(searchParams.get("seconds")) || DEFAULT_DEMO_SECONDS;

  useEffect(() => {
    if (!workspaceSlug || !slug || !runId) return;
    let cancelled = false;
    setState({ kind: "loading" });
    fetchDemoPayload(workspaceSlug, slug, runId)
      .then((payload) => {
        if (!cancelled) setState({ kind: "loaded", payload });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            kind: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, slug, runId]);

  const payload = state.kind === "loaded" ? state.payload : null;
  const acts = useMemo(() => payload?.acts ?? [], [payload]);
  const activeId = (searchParams.get("act") as DemoActId | null) ?? "timeline";
  const active = acts.find((a) => a.id === activeId) ?? acts[0] ?? null;

  const playback = usePlayback(demoSeconds, active?.id === "timeline");

  const selectAct = useCallback(
    (id: DemoActId) => {
      setSearchParams(
        (params) => {
          const next = new URLSearchParams(params);
          next.set("act", id);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return;
      if (event.key === " ") {
        event.preventDefault();
        playback.toggle();
      } else if (event.key.toLowerCase() === "r") {
        playback.restart();
      } else if (event.key === "ArrowRight") {
        playback.seek(playback.progress + 0.02);
      } else if (event.key === "ArrowLeft") {
        playback.seek(playback.progress - 0.02);
      } else if (/^[1-9]$/.test(event.key)) {
        const target = acts[Number(event.key) - 1];
        if (target) selectAct(target.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [acts, playback, selectAct]);

  if (state.kind === "loading") {
    return (
      <Shell>
        <p className="text-[var(--demo-dim)]">Loading the run…</p>
      </Shell>
    );
  }

  if (state.kind === "error") {
    return (
      <Shell>
        <div className="max-w-[60ch]">
          <p className="mb-3 text-xl">{state.message}</p>
          <p className="text-[var(--demo-dim)]">
            Sign in and check you're a member of this workspace.
          </p>
          <Link
            to={`/w/${workspaceSlug}/opps/${slug}`}
            className="mt-6 inline-block text-[var(--demo-ink)] underline underline-offset-4"
          >
            Back to the workbench
          </Link>
        </div>
      </Shell>
    );
  }

  if (!payload || !active) {
    return (
      <Shell>
        <p className="text-[var(--demo-dim)]">This run has nothing to show yet.</p>
      </Shell>
    );
  }

  return (
    <Shell>
      <header className="mb-8 flex flex-wrap items-baseline justify-between gap-x-8 gap-y-3">
        <div className="flex flex-wrap items-baseline gap-x-4">
          <h1 className="text-xl font-medium tracking-tight">
            {payload.run.opp_title ?? payload.run.opp_slug}
          </h1>
          <span className="text-sm text-[var(--demo-dim)]">{payload.run.run_id}</span>
        </div>
        <nav className="flex flex-wrap gap-x-6 gap-y-2">
          {acts.map((act, index) => (
            <button
              key={act.id}
              type="button"
              onClick={() => selectAct(act.id)}
              className="border-b-2 pb-0.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--demo-playhead)]"
              style={{
                borderColor: act.id === active.id ? "var(--demo-ink)" : "transparent",
                color: act.available ? "var(--demo-ink)" : "var(--demo-dim)",
              }}
            >
              <span className="mr-2 text-[var(--demo-dim)]">{index + 1}</span>
              {act.title}
            </button>
          ))}
        </nav>
      </header>

      <main className="min-h-0 flex-1">
        {active.available ? (
          <ActStage act={active} playback={playback} />
        ) : (
          <div className="max-w-[60ch]">
            <p className="text-xl">{active.title}</p>
            <p className="mt-3 leading-relaxed text-[var(--demo-dim)]">
              {active.unavailable_reason}
            </p>
          </div>
        )}
      </main>

      <footer className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-[var(--demo-dim)]">
        <button
          type="button"
          onClick={playback.toggle}
          className="text-[var(--demo-ink)] underline underline-offset-4"
        >
          {playback.playing ? "Pause" : "Play"}
        </button>
        <button type="button" onClick={playback.restart} className="underline underline-offset-4">
          Restart
        </button>
        <span>Space plays · number keys change view · arrows step</span>
        <Link
          to={`/w/${workspaceSlug}/opps/${slug}/runs/${runId}`}
          className="ml-auto underline underline-offset-4"
        >
          Open in the workbench
        </Link>
      </footer>
    </Shell>
  );
}

function ActStage({
  act,
  playback,
}: {
  act: DemoAct;
  playback: ReturnType<typeof usePlayback>;
}) {
  switch (act.id) {
    case "timeline":
      return <TimelineAct timeline={act.data as DemoTimeline} playback={playback} />;
    case "time_ledger":
      return <LedgerAct ledger={act.data as DemoLedger} />;
    case "gates":
      return <GatesAct gates={(act.data as { gates: readonly DemoGate[] }).gates} />;
    case "decisions":
      return <DecisionsAct decisions={act.data as DemoDecisions} />;
    default:
      return null;
  }
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="demo-shell flex min-h-screen flex-col px-8 py-8 sm:px-12">{children}</div>
  );
}
