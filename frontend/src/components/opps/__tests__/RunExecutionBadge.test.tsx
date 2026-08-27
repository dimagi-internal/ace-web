import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunExecutionBadge } from "../RunExecutionBadge";

describe("RunExecutionBadge", () => {
  it("says no runner is available rather than 'queued'", () => {
    render(
      <RunExecutionBadge
        state="no_runner_configured"
        detail="no runner can take this session"
      />,
    );
    expect(screen.getByText(/no runner available/i)).toBeInTheDocument();
    expect(screen.queryByText(/^queued$/i)).toBeNull();
  });

  it("distinguishes a runner that is merely offline", () => {
    render(
      <RunExecutionBadge
        state="waiting_for_runner"
        detail="none are reachable right now"
      />,
    );
    expect(screen.getByText(/waiting for a runner/i)).toBeInTheDocument();
  });

  it("never claims a run is working when canopy could not be reached", () => {
    render(<RunExecutionBadge state="unknown" detail="502" />);
    expect(screen.getByText(/state unknown/i)).toBeInTheDocument();
  });

  it("renders nothing for a run that was never dispatched to canopy", () => {
    const { container } = render(
      <RunExecutionBadge state="not_dispatched" detail="" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("surfaces canopy's own reason as the tooltip, not a guess of ours", () => {
    render(
      <RunExecutionBadge
        state="no_runner_configured"
        detail="no runner is assigned to agent ace"
      />,
    );
    expect(screen.getByTitle("no runner is assigned to agent ace")).toBeInTheDocument();
  });

  it("still explains itself when canopy gives no reason", () => {
    render(<RunExecutionBadge state="no_runner_configured" detail="" />);
    expect(screen.getByText(/no runner available/i).getAttribute("title")).toMatch(
      /will not start/i,
    );
  });

  it("flags a dispatch failure destructively", () => {
    render(<RunExecutionBadge state="dispatch_failed" detail="canopy 403: nope" />);
    const el = screen.getByText(/dispatch failed/i);
    expect(el.className).toMatch(/destructive/);
  });

  it("does not colour a no-runner run as an error", () => {
    // It is the day-one NORMAL state with no session-capable runner online.
    // Painting it red would train everyone to ignore red.
    render(<RunExecutionBadge state="no_runner_configured" detail="" />);
    expect(screen.getByText(/no runner available/i).className).not.toMatch(
      /destructive/,
    );
  });
});
