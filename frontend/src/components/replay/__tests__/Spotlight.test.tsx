import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ViewerTarget } from "@/components/viewers/ViewerContext";

import { SPOTLIGHT_MS, Spotlight } from "../Spotlight";
import type { Replay } from "../useReplay";

const ITEMS = [{ type: "file", fileId: "f1", name: "pdd.md" }] as unknown as ViewerTarget[];

/** Just enough of a Replay for the pop-up's keys; `toggle` flips `playing`. */
function fakeReplay(index = 0, total = 5) {
  const r = {
    playing: true,
    beat: { index },
    total,
    hold: vi.fn(),
    next: vi.fn(),
    prev: vi.fn(),
    toggle: vi.fn(() => {
      r.playing = !r.playing;
    }),
  };
  return r;
}

function space() {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: " " }));
  });
}

describe("Spotlight", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("Space pauses, and Space again resumes the replay", () => {
    const replay = fakeReplay();
    const onClose = vi.fn();
    render(<Spotlight items={ITEMS} replay={replay as unknown as Replay} onClose={onClose} />);

    space();
    expect(replay.playing).toBe(false);
    act(() => vi.advanceTimersByTime(SPOTLIGHT_MS * 2));
    expect(onClose).not.toHaveBeenCalled();

    space();
    expect(replay.playing).toBe(true);
    act(() => vi.advanceTimersByTime(SPOTLIGHT_MS));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("resuming on the last beat lets the countdown close it instead of starting over", () => {
    const replay = fakeReplay(4, 5);
    const onClose = vi.fn();
    render(<Spotlight items={ITEMS} replay={replay as unknown as Replay} onClose={onClose} />);

    space();
    space();
    expect(replay.toggle).toHaveBeenCalledOnce();
    act(() => vi.advanceTimersByTime(SPOTLIGHT_MS));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
