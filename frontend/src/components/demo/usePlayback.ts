import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The Demo Player's clock.
 *
 * Drives playback entirely client-side from an already-loaded event list: no
 * socket, no polling, deterministic, and fully offline after first load. That
 * makes the flagship act the lowest-risk surface in a live demo.
 */
export interface Playback {
  /** Playhead position through the run, 0..1. */
  readonly progress: number;
  readonly playing: boolean;
  /** Seconds of demo time elapsed (the small clock). */
  readonly demoElapsed: number;
  /** Total seconds the compressed run takes to cross the screen. */
  readonly demoDuration: number;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  restart: () => void;
  /** Jump the playhead. Pauses, so a presenter can hold on a moment. */
  seek: (progress: number) => void;
}

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

export function usePlayback(demoDurationSeconds: number, enabled: boolean): Playback {
  const [progress, setProgress] = useState(0);
  const [playing, setPlaying] = useState(false);
  const frame = useRef<number | null>(null);
  const startedAt = useRef<number>(0);
  const startedFrom = useRef<number>(0);

  const stop = useCallback(() => {
    if (frame.current !== null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
    }
  }, []);

  const pause = useCallback(() => {
    stop();
    setPlaying(false);
  }, [stop]);

  const play = useCallback(() => {
    if (!enabled || demoDurationSeconds <= 0) return;
    setProgress((current) => {
      startedFrom.current = current >= 1 ? 0 : current;
      return startedFrom.current;
    });
    startedAt.current = performance.now();
    setPlaying(true);
  }, [enabled, demoDurationSeconds]);

  const toggle = useCallback(() => {
    setPlaying((isPlaying) => {
      if (isPlaying) {
        stop();
        return false;
      }
      setProgress((current) => {
        startedFrom.current = current >= 1 ? 0 : current;
        return startedFrom.current;
      });
      startedAt.current = performance.now();
      return true;
    });
  }, [stop]);

  const restart = useCallback(() => {
    stop();
    setProgress(0);
    setPlaying(false);
  }, [stop]);

  const seek = useCallback(
    (next: number) => {
      stop();
      setPlaying(false);
      setProgress(Math.min(1, Math.max(0, next)));
    },
    [stop],
  );

  useEffect(() => {
    if (!playing) return;
    // Reduced motion: advance in coarse steps rather than a continuous sweep,
    // so the playhead reads as a series of positions instead of a glide.
    const reduced = prefersReducedMotion();
    const tick = () => {
      const elapsed = (performance.now() - startedAt.current) / 1000;
      const raw = startedFrom.current + elapsed / demoDurationSeconds;
      const next = reduced ? Math.floor(raw * 40) / 40 : raw;
      if (next >= 1) {
        setProgress(1);
        setPlaying(false);
        frame.current = null;
        return;
      }
      setProgress(next);
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return stop;
  }, [playing, demoDurationSeconds, stop]);

  useEffect(() => stop, [stop]);

  return {
    progress,
    playing,
    demoElapsed: progress * demoDurationSeconds,
    demoDuration: demoDurationSeconds,
    play,
    pause,
    toggle,
    restart,
    seek,
  };
}
