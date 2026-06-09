import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Drop-in `<textarea>` replacement that:
 *  1. Auto-fits to content — `minHeight` is set to `scrollHeight` on every
 *     value change so all text is visible without an internal scrollbar.
 *  2. Stays drag-resizable via `resize-y` — because we set `minHeight` (not
 *     `height`), the user can drag taller than the content; content growth
 *     never hides text.
 *
 * Technique: reset minHeight → "0px" first so scrollHeight reflects content
 * only (not the previous minHeight floor), then set it to the measured
 * scrollHeight. Tailwind sets `box-sizing: border-box` globally, so
 * scrollHeight already includes padding — no extra offset needed.
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
    el.style.minHeight = "0px";
    el.style.minHeight = `${el.scrollHeight}px`;
  }, []);

  // Run after every paint when props.value changes (controlled path).
  React.useLayoutEffect(() => {
    fit();
  }, [props.value, fit]);

  // Also fit on uncontrolled input (safety net).
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
