import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePlayback } from "../usePlayback";

/** Drive requestAnimationFrame by hand so playback is deterministic. */
let frames: FrameRequestCallback[] = [];
let now = 0;

function advance(ms: number) {
  now += ms;
  const due = frames;
  frames = [];
  act(() => {
    due.forEach((cb) => cb(now));
  });
}

beforeEach(() => {
  frames = [];
  now = 0;
  vi.stubGlobal("performance", { now: () => now });
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    frames.push(cb);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
});

afterEach(() => vi.unstubAllGlobals());

describe("usePlayback", () => {
  it("starts paused at the beginning", () => {
    const { result } = renderHook(() => usePlayback(100, true));
    expect(result.current.playing).toBe(false);
    expect(result.current.progress).toBe(0);
  });

  it("advances progress once playing", () => {
    const { result } = renderHook(() => usePlayback(100, true));
    act(() => result.current.toggle());
    expect(result.current.playing).toBe(true);
    advance(25_000); // a quarter of the 100s run
    expect(result.current.progress).toBeCloseTo(0.25, 2);
    advance(25_000);
    expect(result.current.progress).toBeCloseTo(0.5, 2);
  });

  it("holds position when paused, and resumes from there", () => {
    const { result } = renderHook(() => usePlayback(100, true));
    act(() => result.current.toggle());
    advance(30_000);
    act(() => result.current.toggle());
    const held = result.current.progress;
    expect(result.current.playing).toBe(false);
    advance(30_000);
    expect(result.current.progress).toBe(held);

    act(() => result.current.toggle());
    advance(10_000);
    expect(result.current.progress).toBeCloseTo(held + 0.1, 2);
  });

  it("stops itself at the end rather than running past it", () => {
    const { result } = renderHook(() => usePlayback(10, true));
    act(() => result.current.toggle());
    advance(11_000);
    expect(result.current.progress).toBe(1);
    expect(result.current.playing).toBe(false);
  });

  it("replays from the start when toggled after finishing", () => {
    const { result } = renderHook(() => usePlayback(10, true));
    act(() => result.current.toggle());
    advance(11_000);
    expect(result.current.progress).toBe(1);

    act(() => result.current.toggle());
    expect(result.current.playing).toBe(true);
    advance(2_000);
    expect(result.current.progress).toBeLessThan(0.5);
    expect(result.current.progress).toBeGreaterThan(0);
  });

  it("seek pauses and holds, so a presenter can stop on a beat", () => {
    const { result } = renderHook(() => usePlayback(100, true));
    act(() => result.current.toggle());
    advance(10_000);
    act(() => result.current.seek(0.8));
    expect(result.current.playing).toBe(false);
    expect(result.current.progress).toBe(0.8);
    advance(10_000);
    expect(result.current.progress).toBe(0.8);
  });

  it("resumes from a seeked position rather than from where it was", () => {
    const { result } = renderHook(() => usePlayback(100, true));
    act(() => result.current.seek(0.5));
    act(() => result.current.toggle());
    advance(10_000);
    expect(result.current.progress).toBeCloseTo(0.6, 2);
  });

  it("restart returns to the beginning, paused", () => {
    const { result } = renderHook(() => usePlayback(100, true));
    act(() => result.current.toggle());
    advance(40_000);
    act(() => result.current.restart());
    expect(result.current.progress).toBe(0);
    expect(result.current.playing).toBe(false);
  });

  it("reports demo time alongside the run clock", () => {
    const { result } = renderHook(() => usePlayback(200, true));
    act(() => result.current.toggle());
    advance(50_000);
    expect(result.current.demoDuration).toBe(200);
    expect(result.current.demoElapsed).toBeCloseTo(50, 0);
  });

  it("does nothing while replay is off", () => {
    const { result } = renderHook(() => usePlayback(100, false));
    act(() => result.current.play());
    expect(result.current.playing).toBe(false);
    advance(10_000);
    expect(result.current.progress).toBe(0);
  });
});
