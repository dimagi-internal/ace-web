import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { AddTeammateButton } from "../AddTeammateButton";
import { SharePopover } from "../SharePopover";

/**
 * Issue #528 — `+ teammate` and `share` were styled as outline buttons with
 * the same visual weight as the primary `send` button at the composer. They
 * should be de-emphasized to ghost (tertiary) styling.
 *
 * These tests pin the trigger styling to `variant="ghost"` — text-only,
 * no filled background — while ensuring the buttons remain discoverable
 * (accessible name unchanged).
 */
describe("Chat header collaboration buttons (#528)", () => {
  it("renders the + teammate trigger with tertiary styling and accessible text", () => {
    render(<AddTeammateButton slug="some-session" />);
    const trigger = screen.getByRole("button", { name: /\+ teammate/i });
    expect(trigger).toBeInTheDocument();
    // Ghost variant — no `bg-background` / `bg-primary` filled background;
    // muted-foreground text class is the de-emphasis marker we lock in.
    expect(trigger.className).toContain("text-muted-foreground");
    expect(trigger.className).not.toContain("bg-primary");
  });

  it("renders the share trigger with tertiary styling and accessible text", () => {
    render(<SharePopover slug="some-session" workspaceSlug="ws" />);
    const trigger = screen.getByRole("button", { name: /share/i });
    expect(trigger).toBeInTheDocument();
    expect(trigger.className).toContain("text-muted-foreground");
    expect(trigger.className).not.toContain("bg-primary");
  });
});
