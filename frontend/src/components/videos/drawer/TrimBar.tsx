import { useCallback, useRef, type PointerEvent as ReactPointerEvent } from "react";

interface Props {
  sourceDuration: number;
  start: number;
  duration: number;
  onChange: (next: { start_seconds: number; duration_seconds: number }) => void;
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

export function TrimBar({ sourceDuration, start, duration, onChange }: Props) {
  const barRef = useRef<HTMLDivElement>(null);

  const leftPct = (start / sourceDuration) * 100;
  const widthPct = (duration / sourceDuration) * 100;

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
    [start, duration, sourceDuration, onChange],
  );

  const nudge = (handle: "left" | "right", direction: "+" | "-", amount: number) => {
    const sign = direction === "+" ? 1 : -1;
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
        className="absolute inset-y-0 bg-primary/30 border-2 border-primary cursor-grab"
        style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
        onPointerDown={startDrag("move")}
      >
        <button
          type="button"
          data-testid="trim-handle-left"
          aria-label="Trim start handle"
          tabIndex={0}
          onPointerDown={startDrag("left")}
          onKeyDown={onKey("left")}
          className="absolute top-[-4px] bottom-[-4px] left-0 w-[14px] bg-primary border-2 border-background rounded-sm cursor-ew-resize focus:outline-2 focus:outline-amber-400"
        />
        <button
          type="button"
          data-testid="trim-handle-right"
          aria-label="Trim end handle"
          tabIndex={0}
          onPointerDown={startDrag("right")}
          onKeyDown={onKey("right")}
          className="absolute top-[-4px] bottom-[-4px] right-0 w-[14px] bg-primary border-2 border-background rounded-sm cursor-ew-resize focus:outline-2 focus:outline-amber-400"
        />
      </div>
    </div>
  );
}
