import { useMemo, useRef } from "react";

import type { DemoTimeline } from "@/api/demo";

import { bandSegments, bandTicks, revealedEvents, runElapsed, stepFailed } from "./band";
import { buildPhasePalette, phaseColor } from "./phaseColor";
import { clock, duration } from "./time";
import type { Playback } from "./usePlayback";

/**
 * The Time Machine — the run, compressed.
 *
 * The hero is the pair of clocks over the band: one counting real run time,
 * one counting the minutes the room has actually spent. That contrast is the
 * argument the whole player exists to make, so it gets the type scale and
 * everything else stays quiet.
 */
export function TimelineAct({
  timeline,
  playback,
}: {
  timeline: DemoTimeline;
  playback: Playback;
}) {
  const segments = useMemo(() => bandSegments(timeline), [timeline]);
  const ticks = useMemo(() => bandTicks(timeline), [timeline]);
  const palette = useMemo(
    () => buildPhasePalette(segments.map((s) => s.phase)),
    [segments],
  );
  const revealed = useMemo(
    () => revealedEvents(timeline, playback.progress),
    [timeline, playback.progress],
  );

  const elapsed = runElapsed(timeline, playback.progress);
  const hasClock = timeline.timing_source !== "ordinal";
  // In phase mode the run clock is real but per-STEP times are not measured,
  // so the log shows the phase it belongs to instead of inventing a stamp.
  const stepTimesMeasured = timeline.timing_source === "measured";
  const bandRef = useRef<HTMLDivElement>(null);

  const completed = revealed.filter((e) => e.kind === "step_end");
  const current = completed.at(-1);

  const onScrub = (event: React.MouseEvent<HTMLDivElement>) => {
    const box = bandRef.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    playback.seek((event.clientX - box.left) / box.width);
  };

  return (
    <div className="flex h-full flex-col gap-8">
      <div className="flex flex-wrap items-end gap-x-16 gap-y-6">
        <Counter
          label={hasClock ? "Run time" : "Steps"}
          value={
            hasClock
              ? clock(elapsed ?? 0, timeline.wall_seconds ?? 0)
              : `${completed.length} of ${ticks.length}`
          }
          tone="bright"
        />
        <Counter
          label="On screen"
          value={clock(playback.demoElapsed, playback.demoDuration)}
          tone="dim"
        />
        {!hasClock && (
          <p className="max-w-[46ch] text-sm leading-relaxed text-[var(--demo-dim)]">
            This run recorded no times, so the player shows the order its work
            happened in and no clock.
          </p>
        )}
        {timeline.timing_source === "phase" && (
          <p className="max-w-[46ch] text-sm leading-relaxed text-[var(--demo-dim)]">
            This run timed each phase but not each step, so the clock and the
            bands are measured while steps sit inside the phase they ran in.
          </p>
        )}
      </div>

      <div>
        <div
          ref={bandRef}
          onClick={onScrub}
          role="slider"
          tabIndex={0}
          aria-label="Run position"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(playback.progress * 100)}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft") playback.seek(playback.progress - 0.02);
            if (e.key === "ArrowRight") playback.seek(playback.progress + 0.02);
          }}
          className="relative h-24 w-full cursor-pointer overflow-hidden rounded-sm border border-[var(--demo-rule)] bg-[var(--demo-raised)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--demo-playhead)]"
        >
          {segments.map((segment) => (
            <div
              key={segment.phase}
              className="absolute inset-y-0 border-r border-[var(--demo-ground)]"
              style={{
                left: `${segment.start * 100}%`,
                width: `${segment.width * 100}%`,
                background: `color-mix(in srgb, ${phaseColor(palette, segment.phase)} 22%, transparent)`,
              }}
            >
              <span
                className="absolute bottom-1 left-1.5 max-w-[calc(100%-0.75rem)] truncate rounded-sm bg-[var(--demo-ground)]/70 px-1 py-0.5 text-xs font-medium tracking-tight"
                style={{ color: phaseColor(palette, segment.phase) }}
              >
                {segment.label}
              </span>
            </div>
          ))}

          {ticks.map((tick, index) => (
            <div
              key={`${tick.skill}-${index}`}
              className="absolute top-0 h-9 w-px"
              style={{
                left: `${tick.at * 100}%`,
                background: tick.failed ? "var(--demo-alert)" : phaseColor(palette, tick.phase),
                opacity: tick.at <= playback.progress ? 1 : 0.28,
              }}
            />
          ))}

          <div
            className="demo-scan absolute inset-y-0 left-0"
            style={{ width: `${playback.progress * 100}%` }}
          />
          <div
            className="demo-playhead absolute inset-y-0 w-0.5 bg-[var(--demo-playhead)]"
            style={{ left: `${playback.progress * 100}%` }}
          />
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <p className="mb-3 shrink-0 text-sm text-[var(--demo-dim)]">
          {current
            ? `${current.skill_display ?? current.skill} finished`
            : "Press space to start the run."}
        </p>
        <ol className="flex min-h-0 w-full max-w-5xl flex-1 flex-col-reverse justify-end gap-px overflow-y-auto">
          {completed.map((event, index) => (
            <li
              key={`${event.skill}-${event.seq}`}
              className="flex items-baseline gap-4 border-l-2 py-1.5 pl-3 text-sm"
              style={{
                borderColor: stepFailed(event)
                  ? "var(--demo-alert)"
                  : phaseColor(palette, event.phase),
                opacity: index === completed.length - 1 ? 1 : 0.62,
              }}
            >
              <span className="w-28 shrink-0 truncate text-xs text-[var(--demo-dim)]">
                {stepTimesMeasured && event.t !== null && !event.t_estimated
                  ? clock(event.t, timeline.wall_seconds ?? 0)
                  : hasClock
                    ? event.phase_display
                    : `${index + 1}`}
              </span>
              <span className="flex-1 truncate">
                {event.skill_display ?? event.skill}
              </span>
              {stepFailed(event) && (
                <span className="shrink-0 text-xs text-[var(--demo-alert)]">
                  did not pass
                </span>
              )}
              {stepTimesMeasured && (
                <span className="w-16 shrink-0 text-right text-xs text-[var(--demo-dim)]">
                  {duration(event.duration_seconds)}
                </span>
              )}
              <span className="w-40 shrink-0 truncate text-right text-xs text-[var(--demo-dim)]">
                {event.artifacts?.[0]?.name ?? ""}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function Counter({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "bright" | "dim";
}) {
  return (
    <div>
      <div className="text-sm text-[var(--demo-dim)]">{label}</div>
      <div
        className="text-6xl font-light leading-none tracking-tight sm:text-7xl"
        style={{ color: tone === "bright" ? "var(--demo-ink)" : "var(--demo-dim)" }}
      >
        {value}
      </div>
    </div>
  );
}
