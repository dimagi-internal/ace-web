import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FeedbackPayload } from "@/api/feedback";

const fetchFeedback = vi.fn();
vi.mock("@/api/feedback", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/feedback")>()),
  fetchFeedback: (...args: unknown[]) => fetchFeedback(...args),
}));

const { ReviewView } = await import("../ReviewView");

const SOPHIE: FeedbackPayload = {
  schema_version: 1,
  records: [
    {
      slug: "20260727-sophie-feintuch",
      reviewer: "Sophie Feintuch",
      reviewer_email: "sfeintuch@dimagi-associate.com",
      received_at: "2026-07-27",
      channel: "gdoc-comments",
      artifact: "PDD — Household Poverty Targeting Survey",
      artifact_url: "https://docs.google.com/document/d/abc/edit",
      against_run: "20260722-1341",
      responding_run: "20260728-0705",
      items: [
        {
          id: "d",
          anchor: "§5 [ACE] Visit flow",
          verbatim: "visit_outcome is the first question in the form",
        },
      ],
      item_count: 9,
      tally: { comments: 9, shipped: 8, needs_human: 1, unrouted: 0 },
      ledger_body:
        "## \\[d\\] §5 Visit flow\n\n> visit_outcome is the first question\n\n" +
        "- **SHIPPED** · skill fix — ace\\#979 — computed now. — [x](https://github.com/o/ace/issues/979)\n\n" +
        "## \\[a\\] §3 Instrument\n\n> must be required\n\n" +
        "- **SHIPPED** · decision — all fields REQUIRED. — decisions.yaml\\#req\n\n" +
        "## \\[f\\] §6 Duplicates\n\n> 50m tolerance\n\n" +
        "- **SHIPPED** · skill fix — ace\\#984 — surfaced. — [x](https://github.com/o/ace/issues/984)\n" +
        "- **NEEDS YOU** · open question — pick the radius.\n",
      ledger_url: "https://drive/ledger",
      record_url: "https://drive/record",
    },
  ],
};

function withoutLedger(): FeedbackPayload {
  return {
    ...SOPHIE,
    records: [{ ...SOPHIE.records[0], ledger_body: "", ledger_url: "", tally: null }],
  };
}

describe("ReviewView", () => {
  beforeEach(() => {
    fetchFeedback.mockReset();
    fetchFeedback.mockResolvedValue(SOPHIE);
  });

  it("frames the tab as what an outside expert changed", async () => {
    render(<ReviewView oppSlug="hh-poverty-targeting" workspaceSlug="ws1" />);
    expect(await screen.findByText("What an outside expert changed")).toBeInTheDocument();
    expect(screen.getByText("Sophie Feintuch")).toBeInTheDocument();
  });

  it("separates fixes to ACE from changes to this program", async () => {
    // The distinction the ledger's own SHIPPED badge hid: a fix to ACE
    // reaches every future program; a decision changes this one.
    const { container } = render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    await screen.findByText("fixed in ACE itself");
    const text = container.textContent ?? "";
    expect(text).toMatch(/2\s*fixed in ACE itself/);
    expect(text).toMatch(/1\s*changed this program/);
    expect(text).toMatch(/1\s*waiting on a person/);
  });

  it("badges every change by what it changed, not SHIPPED", async () => {
    render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    await screen.findByText("fixed in ACE itself");
    expect(screen.getAllByText("Fixed in ACE")).toHaveLength(2);
    expect(screen.getAllByText("Changed this program")).toHaveLength(1);
    expect(screen.getAllByText("Needs a decision")).toHaveLength(1);
    expect(screen.queryByText("SHIPPED")).not.toBeInTheDocument();
  });

  it("links a fix to the issue that made it", async () => {
    render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    const link = await screen.findByText("ace#979");
    expect(link.closest("a")).toHaveAttribute("href", "https://github.com/o/ace/issues/979");
  });

  it("shows the comments directly when no ledger has been rendered yet", async () => {
    fetchFeedback.mockResolvedValue(withoutLedger());
    render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    // The review has landed; the join hasn't run. Show the words, and say why
    // the "what changed" half is missing rather than implying nothing changed.
    expect(
      await screen.findByText(/visit_outcome is the first question/),
    ).toBeInTheDocument();
    expect(screen.getByText(/hasn\u2019t been worked out/)).toBeInTheDocument();
  });

  it("invites a first review rather than showing an empty page", async () => {
    fetchFeedback.mockResolvedValue({ schema_version: 1, records: [] });
    render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    expect(
      await screen.findByText(/Nobody outside ACE has reviewed this opp yet/),
    ).toBeInTheDocument();
  });

  it("surfaces a load failure instead of looking empty", async () => {
    fetchFeedback.mockRejectedValue(new Error("Couldn't load this opp's reviews (500)."));
    render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    await waitFor(() =>
      expect(
        screen.getByText("Couldn't load this opp's reviews (500)."),
      ).toBeInTheDocument(),
    );
  });
});
