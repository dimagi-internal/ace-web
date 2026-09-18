import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type DemoTimeline, fetchReplay, timelineOf } from "@/api/replay";
import { getStepDetail } from "@/api/opps";

import {
  beatAt,
  beatStops,
  paceToProgress,
  progressToPace,
  revealAt,
  type Beat,
  type Reveal,
} from "./cursor";
import { usePlayback } from "./usePlayback";

/** How long the whole run takes to cross the screen once. */
const DEFAULT_SECONDS = 180;

export interface Replay {
  /** True once the user has turned replay on. Off, the Workbench is normal. */
  readonly active: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly timeline: DemoTimeline | null;
  readonly beat: Beat;
  readonly reveal: Reveal;
  readonly progress: number;
  readonly playing: boolean;
  readonly runElapsedSeconds: number | null;
  readonly demoElapsedSeconds: number;
  readonly demoDurationSeconds: number;
  start: () => void;
  stop: () => void;
  toggle: () => void;
  restart: () => void;
  step: (delta: number) => void;
  seekProgress: (p: number) => void;
  seekSkill: (skill: string) => void;
}

const EMPTY_REVEAL: Reveal = {
  done: new Set<string>(),
  running: new Set<string>(),
  phases: new Set<string>(),
};
const NO_BEAT: Beat = { index: -1, event: null, phase: null, skill: null };

/**
 * Replay state for one run.
 *
 * Fetches the beat stream lazily — nothing happens until someone turns replay
 * on, so the Workbench costs exactly what it did before for everyone who
 * doesn't. Once on, it warms every step's detail in the background so that
 * stepping never waits on Drive mid-demo.
 */
export function useReplay(
  workspaceSlug: string,
  oppSlug: string,
  runId: string | null,
  demoSeconds: number = DEFAULT_SECONDS,
): Replay {
  const [active, setActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<DemoTimeline | null>(null);
  const warmed = useRef<string | null>(null);

  const playback = usePlayback(demoSeconds, active && timeline !== null);

  // Playback advances at a STEADY beat rate rather than sweeping the clock,
  // so every step gets equal screen time no matter how uneven the run's phase
  // spans are. The band stays proportional — see cursor.ts § beatStops.
  const stops = useMemo(() => (timeline ? beatStops(timeline) : []), [timeline]);
  const progress = useMemo(
    () => (stops.length > 1 ? paceToProgress(stops, playback.progress) : playback.progress),
    [stops, playback.progress],
  );

  // Turning replay off, or changing run, resets everything.
  useEffect(() => {
    setActive(false);
    setTimeline(null);
    setError(null);
    warmed.current = null;
  }, [oppSlug, runId, workspaceSlug]);

  const start = useCallback(() => {
    setActive(true);
    if (timeline || loading || !runId) return;
    setLoading(true);
    setError(null);
    fetchReplay(workspaceSlug, oppSlug, runId)
      .then((payload) => {
        const t = timelineOf(payload);
        if (t) setTimeline(t);
        else setError("This run has no completed steps to replay yet.");
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Couldn't load this run's replay."),
      )
      .finally(() => setLoading(false));
  }, [workspaceSlug, oppSlug, runId, timeline, loading]);

  const stop = useCallback(() => {
    setActive(false);
    playback.pause();
  }, [playback]);

  // Warm every step's detail once, in the background, so the pane that follows
  // the cursor is already populated when the cursor arrives. Failures are
  // ignored: this is a cache warm, and the pane's own fetch is the fallback.
  useEffect(() => {
    if (!active || !timeline || !runId) return;
    const key = `${workspaceSlug}/${oppSlug}/${runId}`;
    if (warmed.current === key) return;
    warmed.current = key;
    const skills = Array.from(
      new Set(
        timeline.ladder.flatMap((p) => p.steps.filter((s) => s.ran).map((s) => s.skill)),
      ),
    );
    let cancelled = false;
    void (async () => {
      for (const skill of skills) {
        if (cancelled) return;
        await getStepDetail(workspaceSlug, oppSlug, runId, skill).catch(() => null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [active, timeline, workspaceSlug, oppSlug, runId]);

  const beat = useMemo(
    () => (timeline ? beatAt(timeline, progress) : NO_BEAT),
    [timeline, progress],
  );
  const reveal = useMemo(
    () => (timeline ? revealAt(timeline, beat.index) : EMPTY_REVEAL),
    [timeline, beat.index],
  );

  /** Land the playhead exactly on a beat, in playback's uniform space. */
  const seekBeatIndex = useCallback(
    (index: number) => {
      if (stops.length < 2) return;
      const clamped = Math.min(stops.length - 1, Math.max(0, index));
      playback.seek(clamped / (stops.length - 1));
    },
    [stops, playback],
  );

  const step = useCallback(
    (delta: number) => {
      if (!timeline || timeline.events.length === 0) return;
      seekBeatIndex(beatAt(timeline, progress).index + delta);
    },
    [timeline, progress, seekBeatIndex],
  );

  const seekSkill = useCallback(
    (skill: string) => {
      if (!timeline) return;
      const index = timeline.events.findIndex(
        (e) => e.kind === "step_end" && e.skill === skill,
      );
      if (index >= 0) seekBeatIndex(index);
    },
    [timeline, seekBeatIndex],
  );

  /** A scrub on the band arrives in RUN space; convert before seeking. */
  const seekProgress = useCallback(
    (p: number) => playback.seek(stops.length > 1 ? progressToPace(stops, p) : p),
    [stops, playback],
  );

  const runElapsedSeconds =
    timeline && timeline.timing_source !== "ordinal" && timeline.wall_seconds
      ? progress * timeline.wall_seconds
      : null;

  return {
    active,
    loading,
    error,
    timeline,
    beat,
    reveal,
    progress,
    playing: playback.playing,
    runElapsedSeconds,
    demoElapsedSeconds: playback.demoElapsed,
    demoDurationSeconds: playback.demoDuration,
    start,
    stop,
    toggle: playback.toggle,
    restart: playback.restart,
    step,
    seekProgress,
    seekSkill,
  };
}
