import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type DemoTimeline, fetchReplay, timelineOf } from "@/api/replay";
import { getStepDetail } from "@/api/opps";

import {
  beatAtIndex,
  beatForSkill,
  EMPTY_REVEAL,
  highlightBeats,
  NO_BEAT,
  revealAt,
  type Beat,
  type Reveal,
} from "./cursor";

/** Pause on each step during auto-play — long enough to see what landed,
 *  short enough that a 60-step run plays through in a couple of minutes. */
export const DEFAULT_STEP_MS = 1500;

export interface Replay {
  /** True once someone has turned replay on. Off, the Workbench is normal. */
  readonly active: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly timeline: DemoTimeline | null;
  readonly beat: Beat;
  readonly reveal: Reveal;
  /** Number of beats in the run. */
  readonly total: number;
  readonly playing: boolean;
  /** Next / Prev / Play move only between highlight beats (phase starts, and
   *  finishes that built something, failed, or decided something). */
  readonly highlightsOnly: boolean;
  /** Pop products up over the screen as the beat that made them lands. */
  readonly spotlights: boolean;
  start: () => void;
  stop: () => void;
  toggle: () => void;
  next: () => void;
  prev: () => void;
  restart: () => void;
  /** Jump to a beat. Pauses, so whoever is driving holds where they land. */
  goTo: (index: number) => void;
  goToSkill: (skill: string) => void;
  toggleHighlights: () => void;
  toggleSpotlights: () => void;
  /** While held, auto-play waits — the spotlight holds the beat it's showing. */
  hold: (held: boolean) => void;
}

/**
 * Step-through replay of one run.
 *
 * Fetches the beat stream lazily — nothing happens until someone turns replay
 * on, so the Workbench costs exactly what it did before for everyone who
 * doesn't. Once on, it warms every step's detail in the background so the
 * expanded drawer is already populated when the cursor arrives.
 */
export function useReplay(
  workspaceSlug: string,
  oppSlug: string,
  runId: string | null,
  stepMs: number = DEFAULT_STEP_MS,
  /** Skills that recorded decisions — their finishes are highlight beats. */
  decisionSkills?: ReadonlySet<string>,
): Replay {
  const [active, setActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<DemoTimeline | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [highlightsOnly, setHighlightsOnly] = useState(false);
  const [spotlights, setSpotlights] = useState(true);
  const held = useRef(false);
  const warmed = useRef<string | null>(null);

  const total = timeline?.events.length ?? 0;

  // Changing run resets everything.
  useEffect(() => {
    setActive(false);
    setTimeline(null);
    setError(null);
    setIndex(0);
    setPlaying(false);
    warmed.current = null;
  }, [oppSlug, runId, workspaceSlug]);

  const start = useCallback(() => {
    setActive(true);
    setIndex(0);
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
    setPlaying(false);
  }, []);

  const clamp = useCallback(
    (i: number) => Math.min(Math.max(0, total - 1), Math.max(0, i)),
    [total],
  );

  const goTo = useCallback(
    (i: number) => {
      setPlaying(false);
      setIndex(clamp(i));
    },
    [clamp],
  );
  const highlights = useMemo(
    () => (timeline ? highlightBeats(timeline, decisionSkills) : []),
    [timeline, decisionSkills],
  );
  // Where one step forward / back lands: the adjacent beat, or in highlights
  // mode the adjacent highlight.
  const stepFrom = useCallback(
    (i: number, dir: 1 | -1) => {
      if (!highlightsOnly || highlights.length === 0) return i + dir;
      if (dir === 1) return highlights.find((h) => h > i) ?? total - 1;
      return [...highlights].reverse().find((h) => h < i) ?? 0;
    },
    [highlightsOnly, highlights, total],
  );
  const next = useCallback(() => goTo(stepFrom(index, 1)), [goTo, stepFrom, index]);
  const prev = useCallback(() => goTo(stepFrom(index, -1)), [goTo, stepFrom, index]);
  const restart = useCallback(() => goTo(0), [goTo]);
  const goToSkill = useCallback(
    (skill: string) => {
      if (!timeline) return;
      const i = beatForSkill(timeline, skill);
      if (i >= 0) goTo(i);
    },
    [timeline, goTo],
  );

  const toggle = useCallback(() => {
    if (total === 0) return;
    setPlaying((p) => {
      // Play from the end starts over rather than doing nothing.
      if (!p && index >= total - 1) setIndex(0);
      return !p;
    });
  }, [total, index]);

  // Auto-play: one beat (or highlight) per tick, stopping on the last, and
  // waiting while something holds the current beat.
  useEffect(() => {
    if (!playing || total === 0) return;
    const id = window.setInterval(() => {
      if (held.current) return;
      setIndex((i) => {
        if (i >= total - 1) {
          setPlaying(false);
          return i;
        }
        return Math.min(total - 1, stepFrom(i, 1));
      });
    }, stepMs);
    return () => window.clearInterval(id);
  }, [playing, total, stepMs, stepFrom]);

  const toggleHighlights = useCallback(() => setHighlightsOnly((h) => !h), []);
  const toggleSpotlights = useCallback(() => setSpotlights((v) => !v), []);
  const hold = useCallback((h: boolean) => {
    held.current = h;
  }, []);

  // Warm every step's detail once, in the background. Failures are ignored:
  // this is a cache warm, and the drawer's own fetch is the fallback.
  useEffect(() => {
    if (!active || !timeline || !runId) return;
    const key = `${workspaceSlug}/${oppSlug}/${runId}`;
    if (warmed.current === key) return;
    warmed.current = key;
    const skills = Array.from(
      new Set(timeline.ladder.flatMap((p) => p.steps.filter((s) => s.ran).map((s) => s.skill))),
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
    () => (timeline ? beatAtIndex(timeline, index) : NO_BEAT),
    [timeline, index],
  );
  const reveal = useMemo(
    () => (timeline ? revealAt(timeline, beat.index) : EMPTY_REVEAL),
    [timeline, beat.index],
  );

  return {
    active,
    loading,
    error,
    timeline,
    beat,
    reveal,
    total,
    playing,
    highlightsOnly,
    spotlights,
    start,
    stop,
    toggle,
    next,
    prev,
    restart,
    goTo,
    goToSkill,
    toggleHighlights,
    toggleSpotlights,
    hold,
  };
}
