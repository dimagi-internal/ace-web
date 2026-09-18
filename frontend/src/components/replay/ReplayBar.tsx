import { useEffect, useMemo, useRef } from "react";
import { Pause, Play, RotateCcw, SkipBack, SkipForward, X } from "lucide-react";

import { Button } from "canopy-ui/ui";

import { bandSegments, bandTicks } from "./band";
import { buildPhasePalette, phaseColor } from "./phaseColor";
import { clock } from "./time";
import type { Replay } from "./useReplay";

/**
 * Replay transport for the Phases screen.
 *
 * The band is the run: each phase takes its measured share of it, ticks mark
 * where each skill finished, and the playhead sweeps. Below it, two clocks —
 * how long the run actually took, against how long you have been watching.
 * That contrast is the point of replaying at all.
 *
 * Keyboard-first, because whoever is driving this is usually talking over it:
 * space plays, arrows step one beat, R restarts.
 */
export function ReplayBar({ replay }: { replay: Replay }) {
  const { timeline } = replay;
  const bandRef = useRef<HTMLDivElement>(null);

  const segments = useMemo(() => (timeline ? bandSegments(timeline) : []), [timeline]);
  const ticks = useMemo(() => (timeline ? bandTicks(timeline) : []), [timeline]);
  const palette = useMemo(
    () => buildPhasePalette(segments.map((s) => s.phase)),
    [segments],
  );

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
        replay.step(1);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        replay.step(-1);
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

  const hasClock = timeline.timing_source !== "ordinal";
  const onScrub = (e: React.MouseEvent<HTMLDivElement>) => {
    const box = bandRef.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    replay.seekProgress((e.clientX - box.left) / box.width);
  };

  return (
    <div className="mb-4 rounded-md border bg-card p-3">
      <div className="mb-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-1">
          <Button size="icon" variant="ghost" onClick={() => replay.step(-1)} title="Back one step">
            <SkipBack className="size-4" />
          </Button>
          <Button size="icon" variant="secondary" onClick={replay.toggle} title="Play or pause (space)">
            {replay.playing ? <Pause className="size-4" /> : <Play className="size-4" />}
          </Button>
          <Button size="icon" variant="ghost" onClick={() => replay.step(1)} title="Forward one step">
            <SkipForward className="size-4" />
          </Button>
          <Button size="icon" variant="ghost" onClick={replay.restart} title="Back to the start (R)">
            <RotateCcw className="size-4" />
          </Button>
        </div>

        {hasClock ? (
          <div className="flex items-baseline gap-5">
            <Readout label="Run time" value={clock(replay.runElapsedSeconds ?? 0, timeline.wall_seconds ?? 0)} strong />
            <Readout label="Watching" value={clock(replay.demoElapsedSeconds, replay.demoDurationSeconds)} />
          </div>
        ) : (
          <Readout
            label="Step"
            value={`${replay.reveal.done.size} of ${ticks.length}`}
            strong
          />
        )}

        <p className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {describe(replay)}
        </p>

        <Button size="sm" variant="ghost" onClick={replay.stop} title="Leave replay (esc)">
          <X className="mr-1 size-3.5" />
          Exit replay
        </Button>
      </div>

      <div
        ref={bandRef}
        onClick={onScrub}
        role="slider"
        tabIndex={0}
        aria-label="Run position"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(replay.progress * 100)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") replay.step(-1);
          if (e.key === "ArrowRight") replay.step(1);
        }}
        className="relative h-8 w-full cursor-pointer overflow-hidden rounded-sm border bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        {segments.map((segment) => {
          const color = phaseColor(palette, segment.phase);
          return (
            <div
              key={segment.phase}
              className="absolute inset-y-0"
              style={{
                left: `${segment.start * 100}%`,
                width: `${segment.width * 100}%`,
                background: `color-mix(in srgb, ${color} ${
                  segment.phase === replay.beat.phase ? 55 : 28
                }%, transparent)`,
              }}
              title={segment.label}
            />
          );
        })}
        {ticks.map((tick, i) => (
          <div
            key={`${tick.skill}-${i}`}
            className="absolute top-0 h-3 w-px"
            style={{
              left: `${tick.at * 100}%`,
              background: tick.failed
                ? "var(--destructive)"
                : phaseColor(palette, tick.phase),
              opacity: tick.at <= replay.progress ? 1 : 0.3,
            }}
          />
        ))}
        <div
          className="absolute inset-y-0 w-0.5 bg-foreground"
          style={{ left: `${replay.progress * 100}%` }}
        />
      </div>

      {timeline.timing_source === "phase" && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          This run timed each phase but not each step, so the clock and the bands
          are measured while steps sit inside the phase they ran in.
        </p>
      )}
    </div>
  );
}

function describe(replay: Replay): string {
  const e = replay.beat.event;
  if (!e) return "Press space to run it, or step through with the arrow keys.";
  if (e.kind === "phase_start") return `Starting ${e.phase_display}`;
  if (e.kind === "step_start") return `Running ${e.skill_display ?? e.skill}`;
  const failed = e.judge?.passed === false || e.qa_result?.verdict === "fail";
  return `${e.skill_display ?? e.skill} ${failed ? "did not pass" : "finished"}`;
}

function Readout({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className="shrink-0">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div
        className={`tabular-nums leading-none ${
          strong ? "text-xl text-foreground" : "text-xl text-muted-foreground"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-center gap-3 rounded-md border bg-card p-3 text-sm text-muted-foreground">
      {children}
    </div>
  );
}
