import { useEffect, useMemo } from "react";
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw, X } from "lucide-react";

import { Button } from "canopy-ui/ui";
import type { DemoEvent, DemoTimeline } from "@/api/replay";

import { stepFailed } from "./cursor";
import { buildPhasePalette, phaseColor } from "./phaseColor";
import type { Replay } from "./useReplay";

/**
 * Step-through controls for the Phases screen.
 *
 * Next / Prev walk the run one step at a time; Play walks it on a short delay.
 * The track below is the run's steps laid out evenly — one slot per step, not
 * per minute — grouped and coloured by phase, so you can see where you are
 * and jump anywhere with a click.
 *
 * Keyboard-first, because whoever drives this is usually talking over it:
 * → next, ← back, space play/pause, R start over, Esc leave.
 */
export function ReplayBar({ replay }: { replay: Replay }) {
  const { timeline } = replay;

  useEffect(() => {
    if (!replay.active) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (target?.isContentEditable) return;
      if (e.key === " ") {
        e.preventDefault();
        replay.toggle();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        replay.next();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        replay.prev();
      } else if (e.key.toLowerCase() === "r") {
        replay.restart();
      } else if (e.key === "Escape") {
        replay.stop();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [replay]);

  if (replay.loading) {
    return <Shell>Loading the run…</Shell>;
  }
  if (replay.error) {
    return (
      <Shell>
        <span className="text-destructive">{replay.error}</span>
        <Button size="sm" variant="ghost" onClick={replay.stop} className="ml-auto">
          Close
        </Button>
      </Shell>
    );
  }
  if (!timeline) return null;

  const atStart = replay.beat.index <= 0;
  const atEnd = replay.beat.index >= replay.total - 1;

  return (
    <div className="mb-4 rounded-md border bg-card p-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            onClick={replay.restart}
            disabled={atStart}
            title="Start over (R)"
          >
            <RotateCcw className="size-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={replay.prev}
            disabled={atStart}
            title="Previous step (←)"
          >
            <ChevronLeft className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={replay.toggle}
            title="Play or pause (space)"
            className="w-20"
          >
            {replay.playing ? (
              <>
                <Pause className="mr-1 size-3.5" /> Pause
              </>
            ) : (
              <>
                <Play className="mr-1 size-3.5" /> {atEnd ? "Replay" : "Play"}
              </>
            )}
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={replay.next}
            disabled={atEnd}
            title="Next step (→)"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>

        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          Step {replay.beat.index + 1} of {replay.total}
        </span>

        <p className="min-w-0 flex-1 truncate text-sm text-foreground">
          <Describe event={replay.beat.event} />
        </p>

        <Button size="sm" variant="ghost" onClick={replay.stop} title="Leave replay (Esc)">
          <X className="mr-1 size-3.5" />
          Exit replay
        </Button>
      </div>

      <StepTrack
        timeline={timeline}
        current={replay.beat.index}
        onPick={replay.goTo}
      />
    </div>
  );
}

function Describe({ event }: { event: DemoEvent | null }) {
  if (!event) return <>Press Play, or use → to step through the run.</>;
  if (event.kind === "phase_start") {
    return (
      <>
        <span className="text-muted-foreground">Starting phase </span>
        {event.phase_display}
      </>
    );
  }
  const name = event.skill_display ?? event.skill ?? "";
  if (event.kind === "step_start") {
    return (
      <>
        <span className="text-muted-foreground">Running </span>
        {name}
      </>
    );
  }
  return stepFailed(event) ? (
    <>
      {name} <span className="text-destructive">did not pass its own review</span>
    </>
  ) : (
    <>
      {name} <span className="text-muted-foreground">finished</span>
    </>
  );
}

interface PhaseRun {
  readonly phase: string;
  readonly label: string;
  readonly from: number;
  readonly count: number;
}

/**
 * The run's steps, grouped into phases that share the width EQUALLY.
 *
 * Every phase gets the same slice of the bar and its steps divide that slice.
 * Neither time-proportional (one idle phase can hold most of a run's hours)
 * nor step-proportional (a two-step phase shrank until its name was cut to
 * "Scenarios & Acceptanc…") — the phases are what a viewer reads, so each one
 * gets room for its name.
 */
function StepTrack({
  timeline,
  current,
  onPick,
}: {
  timeline: DemoTimeline;
  current: number;
  onPick: (i: number) => void;
}) {
  const events = timeline.events;
  const runs = useMemo<PhaseRun[]>(() => {
    const out: PhaseRun[] = [];
    events.forEach((e, i) => {
      const last = out.at(-1);
      if (last && last.phase === e.phase) {
        out[out.length - 1] = { ...last, count: last.count + 1 };
      } else {
        out.push({ phase: e.phase, label: e.phase_display || e.phase, from: i, count: 1 });
      }
    });
    return out;
  }, [events]);
  const palette = useMemo(() => buildPhasePalette(runs.map((r) => r.phase)), [runs]);

  return (
    <div className="mt-3 flex w-full gap-0.5" role="list" aria-label="Steps in this run">
      {runs.map((run) => {
        const color = phaseColor(palette, run.phase);
        const containsCurrent = current >= run.from && current < run.from + run.count;
        return (
          <div
            key={`${run.phase}-${run.from}`}
            className="flex min-w-0 flex-col gap-1"
            style={{ flexGrow: 1, flexBasis: 0 }}
          >
            <div className="flex h-3 gap-px">
              {Array.from({ length: run.count }, (_, k) => {
                const i = run.from + k;
                const e = events[i];
                const failed = e.kind === "step_end" && stepFailed(e);
                const reached = i <= current;
                return (
                  <button
                    key={i}
                    type="button"
                    role="listitem"
                    onClick={() => onPick(i)}
                    title={stepTitle(e)}
                    aria-label={stepTitle(e)}
                    aria-current={i === current ? "step" : undefined}
                    className="min-w-0 flex-1 rounded-[1px] transition-opacity focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
                    style={{
                      background: failed ? "var(--destructive)" : color,
                      opacity: i === current ? 1 : reached ? 0.7 : 0.18,
                      boxShadow: i === current ? "0 0 0 2px var(--foreground)" : undefined,
                    }}
                  />
                );
              })}
            </div>
            <span
              className="line-clamp-2 break-words text-[10px] leading-tight"
              style={{
                color: containsCurrent ? color : "var(--muted-foreground)",
                fontWeight: containsCurrent ? 600 : 400,
              }}
              title={run.label}
            >
              {run.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function stepTitle(e: DemoEvent): string {
  if (e.kind === "phase_start") return `Starting ${e.phase_display}`;
  const name = e.skill_display ?? e.skill ?? "";
  if (e.kind === "step_start") return `Running ${name}`;
  return stepFailed(e) ? `${name} — did not pass` : `${name} — finished`;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-center gap-3 rounded-md border bg-card p-3 text-sm text-muted-foreground">
      {children}
    </div>
  );
}
