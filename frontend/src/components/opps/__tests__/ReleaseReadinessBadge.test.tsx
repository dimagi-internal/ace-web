import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReleaseCheck, ReleasePlan } from "@/api/types.ws";

import { ReleaseReadinessBadge } from "../ReleaseReadinessBadge";

const base: ReleaseCheck = {
  verdict: "NOT_READY", checked_at: "2026-10-01T20:00:00Z", run_last_write: null, read_only: false,
  counts: { blockers: 1, warnings: 0 },
  blockers: [{ id: "deck", area: "eval", owner: "training-deck-render", detail: "Deck scored 4.66", fix: "Re-render" }],
  warnings: [],
  report: { file_id: "f", url: "https://docs.google.com/document/d/f" },
};

const plan: ReleasePlan = {
  reviewers: [{ email: "a@x.org", role: "viewer" }],
  actions: [
    { step: 1, id: "hq:a@x.org", system: "hq", kind: "hq_invite", email: "a@x.org", target: "spark-hq", role: "App Editor" },
    { step: 2, id: "connect:a@x.org:org", system: "connect", kind: "connect_org_member", email: "a@x.org", target: "org", role: "viewer", shared: false },
    { step: 3, id: "drive:f1", system: "drive", kind: "drive_share", target: "f1", title: "The PDD", url: "https://docs.google.com/document/d/f1", role: "commenter", scope: "anyone_with_link" },
    { step: 4, id: "forward-source", system: "ace-web", kind: "forward_source", target: "dimagi-team/opp/r0", cross_workspace: true },
    { step: 5, id: "ace-web:a@x.org", system: "ace-web", kind: "ace_web_invite", email: "a@x.org", target: "spark", role: "viewer" },
    { step: 6, id: "email:a@x.org", system: "email", kind: "email", email: "a@x.org", target: "a@x.org", subject: "Please review" },
  ],
  not_granted: [{ email: "a@x.org", system: "ocs", reason: "public chat link, no account" }],
  emails: [{ to: "a@x.org", subject: "Please review the run", body: "Hi,\n\nAccept here: {{ACCEPT_LINK}}" }],
};

const readyBase: ReleaseCheck = { ...base, verdict: "READY", counts: { blockers: 0, warnings: 0 }, blockers: [] };

describe("ReleaseReadinessBadge", () => {
  it("says a run was never validated rather than looking fine", () => {
    render(<ReleaseReadinessBadge check={null} />);
    expect(screen.getByText("Not validated")).toBeInTheDocument();
  });

  it("shows blockers and how to fix them", () => {
    render(<ReleaseReadinessBadge check={base} />);
    fireEvent.click(screen.getByRole("button", { name: /Not ready · 1 blocker/ }));
    // An older verdict with no plain fields: its detail and fix lead.
    expect(screen.getByText("Deck scored 4.66")).toBeInTheDocument();
    expect(screen.getByText("Re-render")).toBeInTheDocument();
    expect(screen.getByText("Next step:")).toBeInTheDocument();
    expect(screen.queryByText("Technical detail")).not.toBeInTheDocument();
    expect(screen.getByText(/Release-readiness validation of/)).toBeInTheDocument();
  });

  it("leads with the plain summary and action, keeping the internal text behind a toggle", () => {
    render(
      <ReleaseReadinessBadge
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
    render(<ReleaseReadinessBadge check={{ ...readyBase, read_only: true, release_plan: plan }} />);
    expect(screen.queryByText("Ready to release")).not.toBeInTheDocument();
    expect(screen.getByText("(dry run)")).toBeInTheDocument();
  });

  it("a legacy READY verdict without a plan is NOT shown as ready", () => {
    render(<ReleaseReadinessBadge check={{ ...readyBase, kind: "release-check", release_plan: null }} />);
    expect(screen.queryByText("Ready to release")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Re-validate/ }));
    expect(screen.getByText(/needs a release plan from \/ace:validate-release-readiness/)).toBeInTheDocument();
  });

  it("READY with a plan is ready and shows exactly what release will share", () => {
    render(<ReleaseReadinessBadge check={{ ...readyBase, kind: "release-readiness", release_plan: plan }} />);
    fireEvent.click(screen.getByRole("button", { name: /Ready to release/ }));
    expect(
      screen.getByText("Releasing executes only these share actions — nothing else in the run changes."),
    ).toBeInTheDocument();
    // The grant table: one row per reviewer, one column per system.
    const table = screen.getByRole("table");
    for (const col of ["HQ", "Connect", "Drive", "ace-web", "OCS"]) {
      expect(screen.getByRole("columnheader", { name: col })).toBeInTheDocument();
    }
    expect(table).toHaveTextContent("a@x.org");
    expect(table).toHaveTextContent("App Editor");
    expect(table).toHaveTextContent("Not granted — public chat link, no account");
    // Per-run shares sit under the table.
    expect(screen.getByRole("link", { name: "The PDD" })).toBeInTheDocument();
    expect(screen.getByText(/Forward the already-shared link/)).toBeInTheDocument();
    // Each email, body behind a toggle.
    expect(screen.getByText("Please review the run")).toBeInTheDocument();
    expect(screen.getByText(/\{\{ACCEPT_LINK\}\}/)).toBeInTheDocument();
  });
});
