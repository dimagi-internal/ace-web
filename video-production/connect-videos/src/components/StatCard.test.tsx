import { vi } from "vitest";
vi.mock("remotion", () => ({
  spring: () => 1,
  useCurrentFrame: () => 0,
  useVideoConfig: () => ({ fps: 30, width: 1920, height: 1080, durationInFrames: 60 }),
  // StatCard animates opacity/scale via interpolate(); return the end of the
  // output range so the card renders in its fully-animated-in state.
  interpolate: (_frame: number, _input: readonly number[], output: readonly number[]) =>
    output[output.length - 1],
}));

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { StatCard } from "./StatCard";

describe("StatCard", () => {
  it("renders the big number and caption", () => {
    const { getByText } = render(
      <StatCard big="29%" caption="EBF rate in Nigeria" source="NDHS 2018" />
    );
    expect(getByText("29%")).toBeTruthy();
    expect(getByText("EBF rate in Nigeria")).toBeTruthy();
    expect(getByText(/NDHS 2018/)).toBeTruthy();
  });

  it("omits the source line when not provided", () => {
    const { queryByText } = render(<StatCard big="50%" caption="x" />);
    expect(queryByText(/Source/)).toBeNull();
  });
});
