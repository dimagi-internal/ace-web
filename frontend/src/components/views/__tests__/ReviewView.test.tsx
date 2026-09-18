import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      ledger_body: "## Feedback ledger\n\n* SHIPPED — ace#979",
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

  it("names the reviewer and what they reviewed", async () => {
    render(<ReviewView oppSlug="hh-poverty-targeting" workspaceSlug="ws1" />);
    expect(await screen.findByText("Sophie Feintuch")).toBeInTheDocument();
    expect(
      screen.getByText(/PDD — Household Poverty Targeting Survey/),
    ).toBeInTheDocument();
    expect(screen.getByText(/against run 20260722-1341/)).toBeInTheDocument();
  });

  it("reports the plugin's tally, including what still needs a person", async () => {
    const { container } = render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    expect(await screen.findByText("9 comments")).toBeInTheDocument();
    expect(screen.getByText("8 shipped")).toBeInTheDocument();
    // Split across elements for the count's colour, so read the rendered text.
    expect(container.textContent).toContain("1 still needs a person");
  });

  it("uses plural only when more than one item needs a person", async () => {
    fetchFeedback.mockResolvedValue({
      ...SOPHIE,
      records: [
        {
          ...SOPHIE.records[0],
          tally: { comments: 9, shipped: 6, needs_human: 3, unrouted: 0 },
        },
      ],
    });
    const { container } = render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    await screen.findByText("9 comments");
    expect(container.textContent).toContain("3 still need a person");
  });

  it("calls out unrouted items, because those are the ones nobody actioned", async () => {
    fetchFeedback.mockResolvedValue({
      ...SOPHIE,
      records: [
        {
          ...SOPHIE.records[0],
          tally: { comments: 9, shipped: 7, needs_human: 0, unrouted: 2 },
        },
      ],
    });
    const { container } = render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    await screen.findByText("9 comments");
    expect(container.textContent).toContain("2 unrouted");
  });

  it("says which run answered the review", async () => {
    const { container } = render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    await screen.findByText("Sophie Feintuch");
    expect(container.textContent).toContain("Answered in run 20260728-0705");
  });

  it("renders the ledger the plugin published", async () => {
    render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    await screen.findByText("Sophie Feintuch");
    expect(screen.getByText(/ace#979/)).toBeInTheDocument();
  });

  it("can reveal the reviewer's own words alongside the ledger", async () => {
    render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    await screen.findByText("Sophie Feintuch");
    expect(
      screen.queryByText(/visit_outcome is the first question/),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(/Show the original comments/));
    expect(
      screen.getByText(/visit_outcome is the first question/),
    ).toBeInTheDocument();
  });

  it("shows the comments directly when no ledger has been rendered yet", async () => {
    fetchFeedback.mockResolvedValue(withoutLedger());
    render(<ReviewView oppSlug="o" workspaceSlug="ws1" />);
    // The review has landed; the join hasn't run. Show the words, and say why
    // the "what changed" half is missing rather than implying nothing changed.
    expect(
      await screen.findByText(/visit_outcome is the first question/),
    ).toBeInTheDocument();
    expect(screen.getByText(/hasn't been rendered yet/)).toBeInTheDocument();
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
