import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Drop-in `<textarea>` replacement that:
 *  1. Auto-fits to content — the box grows AND shrinks so all text is visible
 *     without an internal scrollbar.
 *  2. Stays drag-resizable (`resize-y`) — a manual drag height is preserved,
 *     and the content floor never lets text be clipped below it.
 *
 * The measurement is the load-bearing part. To read the true content height we
 * must momentarily collapse the box (`height: auto`); reading `scrollHeight`
 * while the box is taller than its content (e.g. after a manual drag, or after
 * deleting text) returns the *box* height, not the content height, which is why
 * a naive `minHeight = scrollHeight` gets stuck. So each fit:
 *   - remembers any explicit (manually-dragged) height,
 *   - drops the min floor and sets `height: auto` to measure content,
 *   - restores the remembered height (drag persists),
 *   - sets `minHeight` to the measured content height (never clips text).
 * All synchronous in one frame, so there's no flicker. With no manual drag the
 * restored height is empty, so the box simply equals its content. Tailwind sets
 * `box-sizing: border-box` globally, so `scrollHeight` already includes padding.
 */
export const AutoResizeTextarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentPropsWithoutRef<"textarea">
>(({ className, rows = 2, onInput, ...props }, forwardedRef) => {
  const innerRef = React.useRef<HTMLTextAreaElement | null>(null);

  // Merge forwardedRef + innerRef so callers can still access the element.
  const ref = React.useCallback(
    (el: HTMLTextAreaElement | null) => {
      innerRef.current = el;
      if (typeof forwardedRef === "function") {
        forwardedRef(el);
      } else if (forwardedRef) {
        (forwardedRef as React.MutableRefObject<HTMLTextAreaElement | null>).current = el;
      }
    },
    [forwardedRef],
  );

  const fit = React.useCallback(() => {
    const el = innerRef.current;
    if (!el) return;
    const manualHeight = el.style.height; // preserve a dragged height, if any
    el.style.minHeight = "0px";
    el.style.height = "auto"; // collapse so scrollHeight = content, not box
    const content = el.scrollHeight;
    el.style.height = manualHeight; // restore the manual height (drag persists)
    el.style.minHeight = `${content}px`; // content floor — text is never clipped
  }, []);

  // Fit on mount and on every controlled-value change.
  React.useLayoutEffect(() => {
    fit();
  }, [props.value, fit]);

  // Re-fit when the box's width changes (rail collapse / window resize): line
  // wrapping changes the content height. Only react to width deltas to avoid a
  // feedback loop with our own height writes.
  React.useEffect(() => {
    const el = innerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let lastWidth = el.clientWidth;
    const ro = new ResizeObserver(() => {
      const node = innerRef.current;
      if (!node) return;
      if (node.clientWidth !== lastWidth) {
        lastWidth = node.clientWidth;
        fit();
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  // Also fit on raw input (uncontrolled usage / pre-React-render safety net).
  const handleInput = React.useCallback(
    (e: React.InputEvent<HTMLTextAreaElement>) => {
      fit();
      onInput?.(e);
    },
    [fit, onInput],
  );

  return (
    <textarea
      ref={ref}
      rows={rows}
      onInput={handleInput}
      className={cn("resize-y", className?.replace(/\bresize-none\b/g, ""))}
      {...props}
    />
  );
});

AutoResizeTextarea.displayName = "AutoResizeTextarea";
