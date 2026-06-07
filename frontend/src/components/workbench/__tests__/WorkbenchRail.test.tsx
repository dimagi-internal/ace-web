import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { WorkbenchRail } from "../WorkbenchRail";

describe("WorkbenchRail (push mode)", () => {
  it("renders title + content when expanded", () => {
    render(
      <WorkbenchRail side="right" title="Chat" collapsed={false} onToggle={() => {}}>
        <div>pane body</div>
      </WorkbenchRail>,
    );
    expect(screen.getByText("Chat")).toBeInTheDocument();
    expect(screen.getByText("pane body")).toBeInTheDocument();
  });

  it("hides content and shows the expand affordance when collapsed", () => {
    render(
      <WorkbenchRail side="right" title="Chat" collapsed onToggle={() => {}}>
        <div>pane body</div>
      </WorkbenchRail>,
    );
    expect(screen.queryByText("pane body")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /show chat/i })).toBeInTheDocument();
  });

  it("calls onToggle when the collapse button is clicked", () => {
    const onToggle = vi.fn();
    render(
      <WorkbenchRail side="right" title="Chat" collapsed={false} onToggle={onToggle}>
        <div>pane body</div>
      </WorkbenchRail>,
    );
    fireEvent.click(screen.getByRole("button", { name: /hide chat/i }));
    expect(onToggle).toHaveBeenCalledOnce();
  });
});

describe("WorkbenchRail overlay mode", () => {
  it("keeps content mounted but aria-hidden when collapsed", () => {
    render(
      <WorkbenchRail side="right" title="Inspector" mode="overlay" collapsed onToggle={() => {}}>
        <div>overlay body</div>
      </WorkbenchRail>,
    );
    const region = screen.getByRole("complementary", { hidden: true });
    expect(region).toHaveAttribute("aria-hidden", "true");
    // Body stays mounted (its state survives a slide-out), just hidden.
    expect(screen.getByText("overlay body")).toBeInTheDocument();
  });

  it("is visible (aria-hidden false) when expanded in overlay mode", () => {
    render(
      <WorkbenchRail side="right" title="Inspector" mode="overlay" collapsed={false} onToggle={() => {}}>
        <div>overlay body</div>
      </WorkbenchRail>,
    );
    expect(screen.getByRole("complementary")).toHaveAttribute("aria-hidden", "false");
  });
});
