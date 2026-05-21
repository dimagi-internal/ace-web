import { useCallback, useEffect, useRef, type RefObject } from "react";

/**
 * Sticky-bottom auto-scroll for a streaming message list.
 *
 * Behaviour:
 *  - When the user is at (or within `thresholdPx` of) the bottom of the
 *    scroll container, growth of `dep` (e.g. messages array, streaming
 *    text length) snaps the view to the new bottom.
 *  - When the user has scrolled up to read history, growth does NOT
 *    yank them back. Auto-follow resumes once they scroll back near
 *    the bottom themselves.
 *
 * The "near bottom" predicate is updated in two places:
 *  - on the user's `scroll` event (so manual scroll-up disables follow)
 *  - immediately after an auto-scroll write (so we stay sticky even
 *    though the scroll event for our own write would temporarily make
 *    `scrollHeight - scrollTop - clientHeight` larger by a few pixels)
 *
 * Use "instant" scroll behavior for streaming chunks — smooth scroll
 * cannot keep up with high-frequency updates and the view drifts.
 *
 * Returns:
 *  - `containerRef`: attach to the scrollable element.
 *  - `onScroll`: attach to `onScroll` on the same element.
 *  - `scrollToBottom`: force a snap (e.g. on send).
 */
export function useStickyBottom<T>(
  dep: T,
  options: { thresholdPx?: number; enabled?: boolean } = {},
): {
  containerRef: RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  scrollToBottom: () => void;
} {
  const { thresholdPx = 100, enabled = true } = options;
  const containerRef = useRef<HTMLDivElement>(null);
  // Default true: when the container first mounts there's no history
  // to read, so the user is "at the bottom" by definition.
  const wasNearBottomRef = useRef(true);

  const isNearBottom = useCallback(
    (el: HTMLElement): boolean =>
      el.scrollHeight - el.scrollTop - el.clientHeight < thresholdPx,
    [thresholdPx],
  );

  const onScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    wasNearBottomRef.current = isNearBottom(el);
  }, [isNearBottom]);

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    wasNearBottomRef.current = true;
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const el = containerRef.current;
    if (!el) return;
    if (wasNearBottomRef.current) {
      // "instant" by direct scrollTop write — smooth scroll falls
      // behind during streaming and the view drifts.
      el.scrollTop = el.scrollHeight;
    }
    // dep is intentionally the only signal that triggers a follow;
    // it should change whenever the message list grows (length or
    // the last message's content length).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dep, enabled]);

  return { containerRef, onScroll, scrollToBottom };
}
