import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as structureApi from "../../api/structure";
import type { StructureTree } from "../../api/types.ws";
import { StructureTab } from "./StructureTab";

/**
 * The last browser-level coverage of this view (upload-flow.spec.ts's
 * "imported session renders messages" e2e) was removed when the legacy
 * chat page it drove through (`/chat/:slug`) was retired — see
 * .superpowers/sdd/2026-07-25-canopy-chat-cutover/task-6-report.md.
 * `SessionStructurePage` (the surviving read-only view, now linked from
 * SessionsPage/OppChatChildren instead) still needs coverage that a real
 * parsed transcript renders correctly.
 *
 * The backend half — raw JSONL → StructureTree — is already covered at
 * the unit level (apps/ingest/tests/test_structure_aggregator.py) and the
 * API contract level (apps/sessions/tests/test_api.py::test_structure_*).
 * What was never covered anywhere is the *frontend* half: does StructureTab
 * turn a StructureTree response into the right DOM — phase/skill rows,
 * wall-time/cost/token stats, expand-to-reveal, and the unavailable-reason
 * fallback copy. That's pure rendering logic, fully exercisable without a
 * browser, so a component test (mocking the API client) is the right level
 * here rather than resurrecting an e2e spec.
 */
describe("StructureTab", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const fullTree: StructureTree = {
    schema_version: 1,
    session: {
      wall_time_seconds: 125,
      estimated_cost_usd: 1.2345,
      cost_is_partial: false,
      tokens: {
        input_tokens: 1000,
        output_tokens: 2000,
        cache_creation_tokens: 500,
        cache_read_tokens: 500,
      },
      status: "ok",
    },
    phases: [
      {
        kind: "phase",
        name: "idea-to-design",
        display: "Idea to Design",
        ordinal: 1,
        wall_time_seconds: 60,
        estimated_cost_usd: 0.5,
        cost_is_partial: false,
        tokens: { input_tokens: 100, output_tokens: 200, cache_creation_tokens: 0, cache_read_tokens: 0 },
        status: "ok",
        children: [
          {
            kind: "skill",
            name: "pdd-draft",
            display: "PDD Draft",
            is_subagent: false,
            started_at: null,
            wall_time_seconds: 30,
            estimated_cost_usd: 0.25,
            cost_is_partial: false,
            tokens: { input_tokens: 50, output_tokens: 100, cache_creation_tokens: 0, cache_read_tokens: 0 },
            status: "ok",
            children: [],
          },
        ],
      },
      {
        kind: "phase",
        name: "_other",
        display: "Other",
        ordinal: 999,
        wall_time_seconds: 5,
        estimated_cost_usd: 0.01,
        cost_is_partial: false,
        tokens: { input_tokens: 10, output_tokens: 10, cache_creation_tokens: 0, cache_read_tokens: 0 },
        status: "error",
        children: [],
      },
    ],
  };

  it("renders session-level stats and every phase from a real transcript tree", async () => {
    vi.spyOn(structureApi, "getSessionStructure").mockResolvedValue(fullTree);
    render(<StructureTab slug="sess-1" workspaceSlug="ws" />);

    expect(await screen.findByText("Idea to Design")).toBeInTheDocument();
    expect(screen.getByText("Other")).toBeInTheDocument();
    // Lifecycle phase (ordinal 1-99) gets the "Phase N:" prefix; the pseudo
    // "_other" phase (ordinal 999) does not.
    expect(screen.getByText("Phase 1:")).toBeInTheDocument();
    expect(screen.queryByText("Phase 999:")).not.toBeInTheDocument();

    // Session-level header stats, computed from format.ts helpers.
    expect(screen.getByText("2m 5s")).toBeInTheDocument(); // wall_time_seconds=125
    expect(screen.getByText("$1.23")).toBeInTheDocument(); // estimated_cost_usd=1.2345
    expect(screen.getByText("4.0k")).toBeInTheDocument(); // totalTokens=4000

    // Error-status phase gets the warning icon.
    expect(screen.getByLabelText("error")).toBeInTheDocument();
  });

  it("expands a phase on click to reveal its skill children", async () => {
    vi.spyOn(structureApi, "getSessionStructure").mockResolvedValue(fullTree);
    render(<StructureTab slug="sess-1" workspaceSlug="ws" />);

    await screen.findByText("Idea to Design");
    expect(screen.queryByText("PDD Draft")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Idea to Design"));
    expect(await screen.findByText("PDD Draft")).toBeInTheDocument();
  });

  it("shows the no-raw-jsonl fallback message when the session has no persisted transcript", async () => {
    vi.spyOn(structureApi, "getSessionStructure").mockResolvedValue({
      schema_version: 0,
      session: null,
      phases: [],
      unavailable_reason: "no-raw-jsonl",
    });
    render(<StructureTab slug="sess-2" workspaceSlug="ws" />);

    expect(
      await screen.findByText(/no persisted raw transcript/i),
    ).toBeInTheDocument();
  });

  it("shows the parse-failed fallback message when aggregation errored", async () => {
    vi.spyOn(structureApi, "getSessionStructure").mockResolvedValue({
      schema_version: 0,
      session: null,
      phases: [],
      unavailable_reason: "parse-failed",
    });
    render(<StructureTab slug="sess-3" workspaceSlug="ws" />);

    expect(
      await screen.findByText(/could not parse the persisted transcript/i),
    ).toBeInTheDocument();
  });

  it("surfaces a load error instead of silently rendering nothing", async () => {
    vi.spyOn(structureApi, "getSessionStructure").mockRejectedValue(
      new Error("boom"),
    );
    render(<StructureTab slug="sess-4" workspaceSlug="ws" />);

    expect(await screen.findByText(/failed to load: boom/i)).toBeInTheDocument();
  });
});
