import { useCallback, useRef, type PointerEvent as ReactPointerEvent } from "react";

interface Props {
  sourceDuration: number;
  start: number;
  duration: number;
  onChange: (next: { start_seconds: number; duration_seconds: number }) => void;
  /**
   * When set, the bar renders a fixed-width window of `playWindow`
   * seconds that the user slides along the source. The window can't
   * be resized — only its in-point moves. This matches the renderer's
   * actual playback contract for beat clip slots (playback duration is
   * fixed at `beat.seconds / N`; the trim picks the in-point only).
   *
   * When omitted, the bar falls back to two-handle range-select
   * behavior (kept so callers that genuinely pick a variable-length
   * selection — e.g. a future "free trim" mode — still work).
   */
  playWindow?: number;
}

const MIN_DURATION = 0.3;
const NUDGE_SMALL = 0.1;
const NUDGE_LARGE = 1.0;

function clampValues(start: number, duration: number, sourceDuration: number) {
  const clampedStart = Math.max(0, Math.min(sourceDuration - MIN_DURATION, start));
  const maxDur = sourceDuration - clampedStart;
  const clampedDur = Math.max(MIN_DURATION, Math.min(maxDur, duration));
  return { start_seconds: clampedStart, duration_seconds: clampedDur };
}

function clampStartOnly(start: number, windowSec: number, sourceDuration: number) {
  // Window slides freely until its right edge would pass the source's
  // tail. If the window is wider than the source (rare; shouldn't
  // happen in practice), just pin to 0 so we at least play the head.
  const maxStart = Math.max(0, sourceDuration - windowSec);
  const clampedStart = Math.max(0, Math.min(maxStart, start));
  return {
    start_seconds: clampedStart,
    duration_seconds: Math.min(windowSec, sourceDuration),
  };
}

export function TrimBar({ sourceDuration, start, duration, onChange, playWindow }: Props) {
  const barRef = useRef<HTMLDivElement>(null);

  // Fixed-window mode: the visible region width is locked to
  // playWindow, regardless of what `duration` says. Only the in-point
  // slides. This is the typical mode for beat clip slots — see comment
  // on the `playWindow` prop.
  const fixedMode = typeof playWindow === "number" && playWindow > 0;
  const effectiveDuration = fixedMode ? Math.min(playWindow!, sourceDuration) : duration;
  const leftPct = (start / sourceDuration) * 100;
  const widthPct = (effectiveDuration / sourceDuration) * 100;

  const startDrag = useCallback(
    (mode: "left" | "right" | "move") => (e: ReactPointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const bar = barRef.current;
      if (!bar) return;
      const barRect = bar.getBoundingClientRect();
      const startX = e.clientX;
      const startStart = start;
      const startDur = duration;

      const onMove = (ev: PointerEvent) => {
        const dSec = ((ev.clientX - startX) / barRect.width) * sourceDuration;
        if (fixedMode) {
          // Only the in-point moves; resize is disabled.
          onChange(clampStartOnly(startStart + dSec, playWindow!, sourceDuration));
          return;
        }
        let nextStart = startStart;
        let nextDur = startDur;
        if (mode === "left") {
          nextStart = startStart + dSec;
          nextDur = startDur - dSec;
        } else if (mode === "right") {
          nextDur = startDur + dSec;
        } else {
          nextStart = startStart + dSec;
        }
        onChange(clampValues(nextStart, nextDur, sourceDuration));
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    },
    [start, duration, sourceDuration, onChange, fixedMode, playWindow],
  );

  const nudge = (handle: "left" | "right", direction: "+" | "-", amount: number) => {
    const sign = direction === "+" ? 1 : -1;
    if (fixedMode) {
      // Both arrow keys move the in-point in fixed-window mode.
      onChange(clampStartOnly(start + sign * amount, playWindow!, sourceDuration));
      return;
    }
    if (handle === "left") {
      const nextStart = start + sign * amount;
      const nextDur = duration - sign * amount;
      onChange(clampValues(nextStart, nextDur, sourceDuration));
    } else {
      onChange(clampValues(start, duration + sign * amount, sourceDuration));
    }
  };

  const onKey = (handle: "left" | "right") => (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const amount = e.shiftKey ? NUDGE_LARGE : NUDGE_SMALL;
    nudge(handle, e.key === "ArrowRight" ? "+" : "-", amount);
  };

  return (
    <div
      ref={barRef}
      data-testid="trim-bar"
      className="relative h-9 select-none rounded bg-muted"
      style={{ touchAction: "none" }}
    >
      <div
        data-testid="trim-region"
        className={`absolute inset-y-0 bg-primary/30 border-2 border-primary ${
          fixedMode ? "cursor-grab" : "cursor-grab"
        }`}
        style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
        onPointerDown={startDrag("move")}
        // Make the whole window keyboard-focusable in fixed mode so
        // arrow keys move the in-point without the user needing to
        // hit the (now-hidden) handle buttons.
        tabIndex={fixedMode ? 0 : -1}
        onKeyDown={fixedMode ? onKey("left") : undefined}
        role={fixedMode ? "slider" : undefined}
        aria-label={fixedMode ? "Playback window in source" : undefined}
        aria-valuemin={fixedMode ? 0 : undefined}
        aria-valuemax={fixedMode ? Math.max(0, sourceDuration - (playWindow ?? 0)) : undefined}
        aria-valuenow={fixedMode ? start : undefined}
      >
        {/* The grip-handles are the user's "this is draggable" cue.
            In fixed mode they're decorative (window is one rigid piece);
            in flexible mode they're real resize-handles. The buttons
            still mount in fixed mode so keyboard tab order and aria
            don't change between modes — they just don't dispatch
            resize ops. */}
        <button
          type="button"
          data-testid="trim-handle-left"
          aria-label="Trim start handle"
          tabIndex={fixedMode ? -1 : 0}
          onPointerDown={fixedMode ? undefined : startDrag("left")}
          onKeyDown={fixedMode ? undefined : onKey("left")}
          className={`absolute top-[-4px] bottom-[-4px] left-0 w-[14px] bg-primary border-2 border-background rounded-sm focus:outline-2 focus:outline-amber-400 ${
            fixedMode ? "cursor-grab pointer-events-none" : "cursor-ew-resize"
          }`}
        />
        <button
          type="button"
          data-testid="trim-handle-right"
          aria-label="Trim end handle"
          tabIndex={fixedMode ? -1 : 0}
          onPointerDown={fixedMode ? undefined : startDrag("right")}
          onKeyDown={fixedMode ? undefined : onKey("right")}
          className={`absolute top-[-4px] bottom-[-4px] right-0 w-[14px] bg-primary border-2 border-background rounded-sm focus:outline-2 focus:outline-amber-400 ${
            fixedMode ? "cursor-grab pointer-events-none" : "cursor-ew-resize"
          }`}
        />
      </div>
    </div>
  );
}
