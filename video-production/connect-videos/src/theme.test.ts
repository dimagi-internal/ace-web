import { describe, it, expect } from "vitest";
import { theme } from "./theme";

describe("theme", () => {
  it("exposes a six-character hex for every color token", () => {
    for (const [key, value] of Object.entries(theme.colors)) {
      expect(value, `${key} should be #RRGGBB`).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });

  it("has a primary accent color used by stat cards", () => {
    expect(theme.colors.accent).toBeDefined();
  });

  it("provides a sans-serif font stack", () => {
    expect(theme.fonts.sans).toMatch(/sans-serif/i);
  });
});
