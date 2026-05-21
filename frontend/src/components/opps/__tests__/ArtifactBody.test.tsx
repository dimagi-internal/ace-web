import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { ArtifactBody } from "@/components/opps/ArtifactBody";

// MarkdownRenderer pulls in a non-trivial tree we don't care about for
// this test — we never reach a "loaded" state.
vi.mock("@/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

describe("ArtifactBody — error recovery CTAs (issue #470)", () => {
  const origFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = origFetch;
  });

  it("renders Retry and Open-in-Drive CTAs when the artifact fetch fails", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    }) as unknown as typeof fetch;

    render(
      <ArtifactBody
        workspaceSlug="ws-1"
        slug="opp-a"
        runId="run-001"
        skill="idea-to-pdd"
        artifactName="pdd.md"
        mimeType="text/markdown"
        webViewLink="https://drive.google.com/file/d/abc123/view"
        driveFileId="abc123"
      />,
    );

    await screen.findByText(/couldn't load this artifact/i);

    // Retry CTA exists and is clickable.
    const retry = screen.getByRole("button", { name: /retry load/i });
    expect(retry).toBeInTheDocument();

    // Open-in-Drive CTA points at the supplied web link.
    const driveLink = screen.getByRole("link", { name: /open in drive/i });
    expect(driveLink).toHaveAttribute(
      "href",
      "https://drive.google.com/file/d/abc123/view",
    );
  });

  it("falls back to a constructed Drive URL when only the file_id is available", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    }) as unknown as typeof fetch;

    render(
      <ArtifactBody
        workspaceSlug="ws-1"
        slug="opp-a"
        runId="run-001"
        skill="idea-to-pdd"
        artifactName="pdd.md"
        mimeType="text/markdown"
        driveFileId="fid-from-detail"
      />,
    );

    await screen.findByText(/couldn't load this artifact/i);
    const driveLink = screen.getByRole("link", { name: /open in drive/i });
    expect(driveLink).toHaveAttribute(
      "href",
      "https://drive.google.com/file/d/fid-from-detail/view",
    );
  });

  it("re-fetches when Retry is clicked", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 500, statusText: "boom" })
      .mockResolvedValueOnce({
        ok: true,
        text: async () => "# Hello",
      });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(
      <ArtifactBody
        workspaceSlug="ws-1"
        slug="opp-a"
        runId="run-001"
        skill="idea-to-pdd"
        artifactName="pdd.md"
        mimeType="text/markdown"
        driveFileId="abc"
      />,
    );

    await screen.findByText(/couldn't load this artifact/i);
    fireEvent.click(screen.getByRole("button", { name: /retry load/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId("markdown")).toBeInTheDocument();
  });
});
