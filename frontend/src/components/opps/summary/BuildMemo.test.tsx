import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

// The SAME bytes the backend suite reads: Drive's own `text/markdown` export
// of a memo shaped by ACE's `skills/build-memo`, captured 2026-09-11. One
// fixture for both halves, so the page is tested against what Drive actually
// sends rather than against markdown someone typed.
import MEMO_EXPORT from "../../../../../apps/opps/tests/fixtures/build_memo_markdown_export.md?raw";
import type { OppSummaryPayload } from "@/api/oppSummary";
import { BuildMemo, splitMemo } from "@/components/opps/summary/BuildMemo";

type Memo = NonNullable<OppSummaryPayload["build_memo"]>;

const MEMO: Memo = {
  title: "Build memo",
  url: "https://docs.google.com/document/d/memo-id/edit",
  access: "admin",
  complete: true,
  gaps: [],
  body: MEMO_EXPORT,
};

describe("splitMemo", () => {
  it("drops the title, keeps the intro, and cuts at each ## heading", () => {
    const split = splitMemo(MEMO_EXPORT);
    expect(split.lead).not.toMatch(/^# /);
    expect(split.lead).toContain("How to review:");
    expect(split.sections.map((s) => s.label)).toEqual([
      "1. Every [ACE] latitude taken and every [FIXED] ambiguity hit",
      "2. Deliver app",
      "3. Learn app",
      "4. Opportunity configuration and verification flags",
      "5. Completeness",
    ]);
  });

  it("renders a memo with no ## headings whole, dropping nothing", () => {
    const split = splitMemo("# Title\n\nJust prose.\n\n### A sub-heading\n\nMore.");
    expect(split.sections).toEqual([]);
    expect(split.lead).toBe("Just prose.\n\n### A sub-heading\n\nMore.");
  });

  it("does not cut at a ## line inside a fenced code block", () => {
    const split = splitMemo("## One\n\n```\n## not a heading\n```\n\n## Two\nx");
    expect(split.sections.map((s) => s.label)).toEqual(["One", "Two"]);
    expect(split.sections[0].body).toContain("## not a heading");
  });
});

describe("BuildMemo", () => {
  it("renders section 1 as a real table, escapes resolved", () => {
    render(<BuildMemo memo={MEMO} showAccessTags={false} />);

    const tables = screen.getAllByRole("table");
    const reviewTable = tables[0];
    expect(within(reviewTable).getByText("Where to spot-check")).toBeTruthy();
    expect(
      within(reviewTable).getByText("Deliver app → Household visit → Roster"),
    ).toBeTruthy();
    // `\[ACE\]` in the export renders as `[ACE]`, not with its backslashes.
    expect(within(reviewTable).getByText("[ACE] latitude")).toBeTruthy();
    expect(screen.queryByText(/\\\[ACE\\\]/)).toBeNull();
  });

  it("keeps section 1 open and folds the producers' memos", () => {
    const { container } = render(<BuildMemo memo={MEMO} showAccessTags={false} />);
    const details = Array.from(container.querySelectorAll("details"));
    expect(details.map((d) => d.querySelector("summary")?.textContent)).toEqual([
      "2. Deliver app",
      "3. Learn app",
      "4. Opportunity configuration and verification flags",
      "5. Completeness",
    ]);
    expect(details.every((d) => !d.open)).toBe(true);
    // The review table is not inside any fold.
    expect(screen.getAllByRole("table")[0].closest("details")).toBeNull();
  });

  it("shows no incompleteness notice for a complete memo", () => {
    render(<BuildMemo memo={MEMO} showAccessTags={false} />);
    expect(screen.queryByText("This memo is incomplete")).toBeNull();
  });

  it("puts the gaps above the memo when it is incomplete", () => {
    const { container } = render(
      <BuildMemo
        memo={{
          ...MEMO,
          complete: false,
          gaps: ["4-connect/connect-opp-setup.md: section missing"],
        }}
        showAccessTags={false}
      />,
    );
    const notice = screen.getByText("This memo is incomplete");
    expect(screen.getByText("4-connect/connect-opp-setup.md: section missing")).toBeTruthy();
    const firstTable = container.querySelector("table")!;
    expect(
      notice.compareDocumentPosition(firstTable) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("says a memo is incomplete even when the run recorded no gaps", () => {
    render(
      <BuildMemo memo={{ ...MEMO, complete: false, gaps: [] }} showAccessTags={false} />,
    );
    expect(screen.getByText(/without recording what is missing/)).toBeTruthy();
  });

  it("keeps Google Docs as a secondary link, tagged for an outsider", () => {
    render(<BuildMemo memo={MEMO} showAccessTags />);
    const link = screen.getByText("Open in Google Docs").closest("a")!;
    expect(link.getAttribute("href")).toBe(MEMO.url);
    expect(screen.getByText("admin only")).toBeTruthy();
  });

  it("falls back to the link when the text could not be read", () => {
    render(<BuildMemo memo={{ ...MEMO, body: null }} showAccessTags={false} />);
    expect(screen.getByText(/could not be loaded here/)).toBeTruthy();
    expect(screen.getByText("Open in Google Docs")).toBeTruthy();
  });

  it("never renders raw HTML from the document", () => {
    const { container } = render(
      <BuildMemo
        memo={{
          ...MEMO,
          body: "Intro <script>alert(1)</script> <img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))",
        }}
        showAccessTags={false}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    const a = screen.getByText("x").closest("a")!;
    expect(a.getAttribute("href") ?? "").not.toMatch(/javascript:/i);
  });
});
