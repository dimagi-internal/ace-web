import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Lower3rd } from "./Lower3rd";

describe("Lower3rd", () => {
  it("renders the provided text", () => {
    const { getByText } = render(<Lower3rd text="Nigeria · 2026" />);
    expect(getByText("Nigeria · 2026")).toBeTruthy();
  });
});
