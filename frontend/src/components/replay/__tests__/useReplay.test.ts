import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SAMPLE } from "../__fixtures__/sample";

const fetchReplay = vi.fn();
vi.mock("@/api/replay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/replay")>()),
  fetchReplay: (...a: unknown[]) => fetchReplay(...a),
}));
vi.mock("@/api/opps", () => ({ getStepDetail: vi.fn(() => Promise.resolve(null)) }));

const { useReplay } = await import("../useReplay");

async function started(stepMs = 1000) {
  const hook = renderHook(() => useReplay("ws1", "opp", "run-1", stepMs));
  act(() => hook.result.current.start());
  await waitFor(() => expect(hook.result.current.timeline).not.toBeNull());
  return hook;
}

beforeEach(() => {
  fetchReplay.mockReset();
  fetchReplay.mockResolvedValue(SAMPLE);
});
afterEach(() => vi.useRealTimers());

describe("useReplay — step-through", () => {
  it("is off until someone starts it, and fetches nothing before then", () => {
    const { result } = renderHook(() => useReplay("ws1", "opp", "run-1"));
    expect(result.current.active).toBe(false);
    expect(fetchReplay).not.toHaveBeenCalled();
  });

  it("opens on the first step, paused", async () => {
    const { result } = await started();
    expect(result.current.active).toBe(true);
    expect(result.current.beat.index).toBe(0);
    expect(result.current.playing).toBe(false);
    expect(result.current.total).toBeGreaterThan(10);
  });

  it("steps forward and back one at a time", async () => {
    const { result } = await started();
    act(() => result.current.next());
    act(() => result.current.next());
    expect(result.current.beat.index).toBe(2);
    act(() => result.current.prev());
    expect(result.current.beat.index).toBe(1);
  });

  it("never steps outside the run", async () => {
    const { result } = await started();
    act(() => result.current.prev());
    expect(result.current.beat.index).toBe(0);
    act(() => result.current.goTo(10_000));
    expect(result.current.beat.index).toBe(result.current.total - 1);
    act(() => result.current.next());
    expect(result.current.beat.index).toBe(result.current.total - 1);
  });

  it("play advances one step per tick", async () => {
    const { result } = await started(1000);
    vi.useFakeTimers();
    act(() => result.current.toggle());
    expect(result.current.playing).toBe(true);
    act(() => vi.advanceTimersByTime(3000));
    expect(result.current.beat.index).toBe(3);
  });

  it("pause holds the current step", async () => {
    const { result } = await started(1000);
    vi.useFakeTimers();
    act(() => result.current.toggle());
    act(() => vi.advanceTimersByTime(2000));
    act(() => result.current.toggle());
    const held = result.current.beat.index;
    act(() => vi.advanceTimersByTime(5000));
    expect(result.current.beat.index).toBe(held);
  });

  it("manual stepping pauses auto-play, so the two never fight", async () => {
    const { result } = await started(1000);
    vi.useFakeTimers();
    act(() => result.current.toggle());
    act(() => result.current.next());
    expect(result.current.playing).toBe(false);
  });

  it("stops on the last step, and Play from there starts over", async () => {
    const { result } = await started(10);
    vi.useFakeTimers();
    act(() => result.current.toggle());
    act(() => vi.advanceTimersByTime(10 * (result.current.total + 5)));
    expect(result.current.playing).toBe(false);
    expect(result.current.beat.index).toBe(result.current.total - 1);
    act(() => result.current.toggle());
    expect(result.current.beat.index).toBe(0);
    expect(result.current.playing).toBe(true);
  });

  it("jumps to where a skill finished", async () => {
    const { result } = await started();
    const skill = result.current.timeline!.events.find((e) => e.kind === "step_end")!.skill!;
    act(() => result.current.goToSkill(skill));
    expect(result.current.beat.event?.kind).toBe("step_end");
    expect(result.current.beat.skill).toBe(skill);
  });

  it("reports a load failure instead of hanging", async () => {
    fetchReplay.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useReplay("ws1", "opp", "run-1"));
    act(() => result.current.start());
    await waitFor(() => expect(result.current.error).toBe("boom"));
  });
});
