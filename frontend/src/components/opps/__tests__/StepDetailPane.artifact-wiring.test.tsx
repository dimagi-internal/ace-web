import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { StepDetailPane } from "@/components/opps/StepDetailPane";

vi.mock("@/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

const getStepDetail = vi.fn();
vi.mock("@/api/opps", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return { ...actual, getStepDetail: (...a: unknown[]) => getStepDetail(...a) };
});

/**
 * The step-detail endpoint returns artifacts in ArtifactOut shape —
 * ``id`` / ``url``, NOT ``drive_file_id`` / ``drive_web_link``. The pane
 * read the latter, so every artifact rendered "Couldn't load this
 * artifact" without ever issuing a fetch, and with no Drive fallback
 * link. Nothing caught it: getStepDetail casts through
 * ``as unknown as StepDetail``, and the generated OpenAPI type for these
 * artifacts is the WRONG ``ArtifactOut`` (two ninja schema classes share
 * the name; the apps/system one wins in the schema document).
 *
 * This test pins the pane against the shape the API actually returns.
 */
const API_SHAPE = {
  skill: "idea-to-pdd",
  phase: "idea-to-design",
  status: "complete",
  artifact_count: 1,
  artifacts: [
    {
      id: "1xvS3zX_PkXV7hoRXFCf6y7TdXmoLyh_bU2tWiyoSTIY",
      name: "idea-to-pdd.md",
      mime_type: "application/vnd.google-apps.document",
      size_bytes: 8499,
      url: "https://docs.google.com/document/d/1xvS3zX_PkXV7hoRXFCf6y7TdXmoLyh_bU2tWiyoSTIY/edit",
      is_text: true,
      preview: null,
    },
  ],
  verdicts: [],
  gate: null,
  preview: null,
};

describe("StepDetailPane — artifact identity wiring", () => {
  const origFetch = globalThis.fetch;

  beforeEach(() => {
    getStepDetail.mockReset();
    getStepDetail.mockResolvedValue(API_SHAPE);
  });
  afterEach(() => {
    globalThis.fetch = origFetch;
  });

  it("fetches the artifact body using the id the API returned", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => "# PDD\n\nbody",
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(
      <StepDetailPane
        workspaceSlug="dimagi-team"
        slug="spark-facilitator"
        runId="20260724-1622"
        skill="idea-to-pdd"
      />,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain(
      "/artifacts/1xvS3zX_PkXV7hoRXFCf6y7TdXmoLyh_bU2tWiyoSTIY/download",
    );
    expect(screen.queryByText(/couldn't load this artifact/i)).toBeNull();
  });

  it("offers the Drive link the API returned when the body fetch fails", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    }) as unknown as typeof fetch;

    render(
      <StepDetailPane
        workspaceSlug="dimagi-team"
        slug="spark-facilitator"
        runId="20260724-1622"
        skill="idea-to-pdd"
      />,
    );

    await screen.findByText(/couldn't load this artifact/i);
    const links = screen.getAllByRole("link", { name: /open in drive/i });
    expect(links[0]).toHaveAttribute("href", API_SHAPE.artifacts[0].url);
  });
});
