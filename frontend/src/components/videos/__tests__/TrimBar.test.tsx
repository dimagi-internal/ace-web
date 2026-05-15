import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TrimBar } from "../drawer/TrimBar";

function renderBar(props: Partial<Parameters<typeof TrimBar>[0]> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <TrimBar
      sourceDuration={10}
      start={2}
      duration={4}
      onChange={onChange}
      {...props}
    />,
  );
  return { onChange, ...utils };
}

describe("TrimBar", () => {
  it("renders region positioned proportionally to source duration", () => {
    renderBar();
    const region = screen.getByTestId("trim-region");
    // start=2 of 10 = 20%; dur=4 of 10 = 40%
    expect(region.style.left).toBe("20%");
    expect(region.style.width).toBe("40%");
  });

  it("clamps start ≥ 0", () => {
    const { onChange } = renderBar({ start: 0, duration: 4 });
    const left = screen.getByTestId("trim-handle-left");
    // Mock a getBoundingClientRect for the bar.
    const bar = screen.getByTestId("trim-bar");
    vi.spyOn(bar, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 200, bottom: 20, width: 200, height: 20, toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(left, { clientX: 0, pointerId: 1 });
    fireEvent.pointerMove(window, { clientX: -100, pointerId: 1 });
    fireEvent.pointerUp(window, { clientX: -100, pointerId: 1 });
    const calls = onChange.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const last = calls[calls.length - 1][0];
    expect(last.start_seconds).toBeGreaterThanOrEqual(0);
  });

  it("clamps start + duration ≤ sourceDuration", () => {
    const { onChange } = renderBar({ start: 6, duration: 4 }); // 10s used of 10s
    const right = screen.getByTestId("trim-handle-right");
    const bar = screen.getByTestId("trim-bar");
    vi.spyOn(bar, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 200, bottom: 20, width: 200, height: 20, toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(right, { clientX: 200, pointerId: 1 });
    fireEvent.pointerMove(window, { clientX: 400, pointerId: 1 });
    fireEvent.pointerUp(window, { clientX: 400, pointerId: 1 });
    const last = onChange.mock.calls.at(-1)![0];
    expect(last.start_seconds + last.duration_seconds).toBeLessThanOrEqual(10 + 0.001);
  });

  it("arrow key nudges focused handle by 0.1s", () => {
    const { onChange } = renderBar();
    const left = screen.getByTestId("trim-handle-left");
    left.focus();
    fireEvent.keyDown(left, { key: "ArrowRight" });
    const last = onChange.mock.calls.at(-1)![0];
    expect(last.start_seconds).toBeCloseTo(2.1, 3);
  });

  it("shift+arrow nudges by 1.0s", () => {
    const { onChange } = renderBar();
    const left = screen.getByTestId("trim-handle-left");
    left.focus();
    fireEvent.keyDown(left, { key: "ArrowRight", shiftKey: true });
    const last = onChange.mock.calls.at(-1)![0];
    expect(last.start_seconds).toBeCloseTo(3.0, 3);
  });
});
