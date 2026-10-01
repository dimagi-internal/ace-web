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
    expect(screen.getByText("Deck scored 4.66")).toBeInTheDocument();
    expect(screen.getByText("Fix: Re-render")).toBeInTheDocument();
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
