import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Textarea that auto-sizes to fit its content ONCE — when the content first
 * loads — then behaves as a normal drag-resizable textarea.
 *
 * So the editor opens with every box sized to show all its text (no internal
 * scrollbars), and after that the user owns each box's size by dragging the
 * `resize-y` handle. Typing after the initial fit does NOT re-grow/shrink the
 * box (it scrolls like a normal textarea) — per the desired behavior:
 * auto-size on open, manual thereafter.
 *
 * The fit runs once, keyed on the arrival of content (the value is empty on the
 * first paint while the template loads, then populated). It re-fits on remount,
 * so keying the editor by template id sizes a freshly-opened template's boxes.
 * Tailwind sets `box-sizing: border-box`, so `scrollHeight` includes padding.
 */
export const AutoResizeTextarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentPropsWithoutRef<"textarea">
>(({ className, rows = 2, ...props }, forwardedRef) => {
  const innerRef = React.useRef<HTMLTextAreaElement | null>(null);
  const fitted = React.useRef(false);

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

  // Fit exactly once, when content first arrives. `height: auto` collapses the
  // box so scrollHeight reflects content, then we pin that height. After this
  // the box is purely manual (resize-y); we never auto-resize again.
  React.useLayoutEffect(() => {
    const el = innerRef.current;
    if (!el || fitted.current) return;
    if (!el.value) return; // wait until the loaded content populates the value
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
    fitted.current = true;
  }, [props.value]);

  return (
    <textarea
      ref={ref}
      rows={rows}
      className={cn("resize-y", className?.replace(/\bresize-none\b/g, ""))}
      {...props}
    />
  );
});

AutoResizeTextarea.displayName = "AutoResizeTextarea";
