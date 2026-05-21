import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useStickyBottom } from "./useStickyBottom";

/**
 * jsdom doesn't lay out elements, so scrollHeight/clientHeight/scrollTop
 * are all 0 by default. Install a minimal stub on a synthetic <div> that
 * lets us drive the sticky-bottom predicate deterministically.
 *
 * The hook reads `scrollHeight`, `scrollTop`, `clientHeight` and writes
 * `scrollTop`. That's it. Everything else jsdom can handle.
 */
function makeFakeContainer(
  initial: { scrollHeight: number; clientHeight: number; scrollTop: number },
): HTMLDivElement & {
  __set: (next: Partial<typeof initial>) => void;
} {
  const el = document.createElement("div");
  const state = { ...initial };
  Object.defineProperty(el, "scrollHeight", {
    configurable: true,
    get: () => state.scrollHeight,
  });
  Object.defineProperty(el, "clientHeight", {
    configurable: true,
    get: () => state.clientHeight,
  });
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => state.scrollTop,
    set: (v: number) => {
      state.scrollTop = v;
    },
  });
  (el as unknown as { __set: (next: Partial<typeof initial>) => void }).__set =
    (next) => Object.assign(state, next);
  return el as HTMLDivElement & {
    __set: (next: Partial<typeof initial>) => void;
  };
}

describe("useStickyBottom", () => {
  it("snaps to bottom when content grows and the user was near the bottom", () => {
    const container = makeFakeContainer({
      // user is exactly at the bottom: 1000 - 600 - 400 = 0 < 100
      scrollHeight: 1000,
      clientHeight: 400,
      scrollTop: 600,
    });

    const { result, rerender } = renderHook(({ dep }) => useStickyBottom(dep), {
      initialProps: { dep: 0 },
    });

    // Attach the ref by hand — renderHook doesn't render JSX.
    (result.current.containerRef as { current: HTMLDivElement | null }).current =
      container;

    // Simulate growth: more content arrives.
    act(() => {
      container.__set({ scrollHeight: 2000 });
    });
    rerender({ dep: 1 });

    // scrollTop should have snapped to the new bottom.
    expect(container.scrollTop).toBe(2000);
  });

  it("does NOT yank the user back when they have scrolled up", () => {
    const container = makeFakeContainer({
      scrollHeight: 1000,
      clientHeight: 400,
      scrollTop: 600, // at bottom initially
    });

    const { result, rerender } = renderHook(({ dep }) => useStickyBottom(dep), {
      initialProps: { dep: 0 },
    });
    (result.current.containerRef as { current: HTMLDivElement | null }).current =
      container;

    // First growth tick (mount-triggered effect already ran). Reset
    // scrollTop so we can detect a fresh write below.
    act(() => {
      container.__set({ scrollTop: 100 }); // user scrolled way up
    });
    act(() => {
      // Fire the scroll handler so the hook records "not near bottom".
      result.current.onScroll();
    });

    // Content grows again while user is up reading history.
    act(() => {
      container.__set({ scrollHeight: 3000 });
    });
    rerender({ dep: 2 });

    // scrollTop must NOT have moved.
    expect(container.scrollTop).toBe(100);
  });

  it("resumes auto-follow once the user scrolls back near the bottom", () => {
    const container = makeFakeContainer({
      scrollHeight: 1000,
      clientHeight: 400,
      scrollTop: 600,
    });

    const { result, rerender } = renderHook(({ dep }) => useStickyBottom(dep), {
      initialProps: { dep: 0 },
    });
    (result.current.containerRef as { current: HTMLDivElement | null }).current =
      container;

    // User scrolls up.
    act(() => {
      container.__set({ scrollTop: 100 });
      result.current.onScroll();
    });

    // Growth while up: no snap.
    act(() => {
      container.__set({ scrollHeight: 2000 });
    });
    rerender({ dep: 1 });
    expect(container.scrollTop).toBe(100);

    // User scrolls back down to within the 100px threshold:
    // 2000 - 1550 - 400 = 50 < 100
    act(() => {
      container.__set({ scrollTop: 1550 });
      result.current.onScroll();
    });

    // More growth: snap should resume.
    act(() => {
      container.__set({ scrollHeight: 3000 });
    });
    rerender({ dep: 2 });
    expect(container.scrollTop).toBe(3000);
  });

  it("scrollToBottom() force-snaps and re-arms sticky tracking", () => {
    const container = makeFakeContainer({
      scrollHeight: 5000,
      clientHeight: 400,
      scrollTop: 100, // scrolled up
    });

    const { result } = renderHook(() => useStickyBottom(0));
    (result.current.containerRef as { current: HTMLDivElement | null }).current =
      container;

    act(() => {
      result.current.onScroll(); // record "not near bottom"
    });

    act(() => {
      result.current.scrollToBottom();
    });
    expect(container.scrollTop).toBe(5000);
  });
});
