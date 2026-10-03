import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReleaseCheck } from "@/api/types.ws";

import { ReleaseCheckBadge } from "../ReleaseCheckBadge";

const base: ReleaseCheck = {
  verdict: "NOT_READY", checked_at: "2026-10-01T20:00:00Z", run_last_write: null, read_only: false,
  counts: { blockers: 1, warnings: 0 },
  blockers: [{ id: "deck", area: "eval", owner: "training-deck-render", detail: "Deck scored 4.66", fix: "Re-render" }],
  warnings: [],
  report: { file_id: "f", url: "https://docs.google.com/document/d/f" },
};

describe("ReleaseCheckBadge", () => {
  it("says a run was never checked rather than looking fine", () => {
    render(<ReleaseCheckBadge check={null} />);
    expect(screen.getByText("Not release-checked")).toBeInTheDocument();
  });

  it("shows blockers and how to fix them", () => {
    render(<ReleaseCheckBadge check={base} />);
    fireEvent.click(screen.getByRole("button", { name: /Not ready · 1 blocker/ }));
    // An older verdict with no plain fields: its detail and fix lead.
    expect(screen.getByText("Deck scored 4.66")).toBeInTheDocument();
    expect(screen.getByText("Re-render")).toBeInTheDocument();
    expect(screen.getByText("Next step:")).toBeInTheDocument();
    expect(screen.queryByText("Technical detail")).not.toBeInTheDocument();
  });

  it("leads with the plain summary and action, keeping the internal text behind a toggle", () => {
    render(
      <ReleaseCheckBadge
        check={{
          ...base,
          blockers: [{
            ...base.blockers[0],
            summary: "The training deck failed its quality review.",
            action: "Re-render the deck, then run the release check again.",
          }],
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Not ready · 1 blocker/ }));
    const lead = screen.getByText("The training deck failed its quality review.");
    const owner = screen.getByText("training-deck-render");
    expect(lead.compareDocumentPosition(owner) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Re-render the deck, then run the release check again.")).toBeInTheDocument();
    // The internal detail is kept, but demoted.
    expect(screen.getByText("Technical detail")).toBeInTheDocument();
    expect(screen.getByText("Deck scored 4.66")).toBeInTheDocument();
  });

  it("a READY dry run is not ready", () => {
    render(<ReleaseCheckBadge check={{ ...base, verdict: "READY", read_only: true, counts: { blockers: 0, warnings: 0 }, blockers: [] }} />);
    expect(screen.queryByText("Ready to release")).not.toBeInTheDocument();
    expect(screen.getByText("(dry run)")).toBeInTheDocument();
  });

  it("READY is ready", () => {
    render(<ReleaseCheckBadge check={{ ...base, verdict: "READY", counts: { blockers: 0, warnings: 0 }, blockers: [] }} />);
    expect(screen.getByRole("button", { name: /Ready to release/ })).toBeInTheDocument();
  });
});
