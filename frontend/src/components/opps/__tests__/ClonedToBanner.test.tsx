import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClonedToBanner } from "../ClonedToBanner";

const listRunClones = vi.fn();
vi.mock("@/api/opps", () => ({
  listRunClones: (...args: unknown[]) => listRunClones(...args),
}));

const base = {
  id: 1,
  source_workspace: "dimagi-team",
  target_workspace: "spark",
  opp_slug: "spark-facilitator",
  run_id: "20260926-1413",
  status: "done",
  files_copied: 120,
  error: "",
  created_by: "owner@dimagi.com",
  created_at: "2026-09-28T00:00:00Z",
  forwards_public_link: false,
};

describe("ClonedToBanner", () => {
  beforeEach(() => listRunClones.mockReset());

  it("renders nothing for a run that was never cloned", async () => {
    listRunClones.mockResolvedValue([]);
    const { container } = render(
      <ClonedToBanner workspaceSlug="dimagi-team" slug="spark-facilitator" runId="r" />,
    );
    await Promise.resolve();
    expect(container.textContent).toBe("");
  });

  it("names the target workspace and says the link forwards", async () => {
    listRunClones.mockResolvedValue([{ ...base, forwards_public_link: true }]);
    render(<ClonedToBanner workspaceSlug="dimagi-team" slug="spark-facilitator" runId="r" />);
    expect(await screen.findByText("spark")).toBeTruthy();
    expect(screen.getByText(/public summary link now opens that copy/)).toBeTruthy();
  });

  it("says edits here do not reach an unforwarded copy, and hides failed clones", async () => {
    listRunClones.mockResolvedValue([base, { ...base, id: 2, target_workspace: "x", status: "error" }]);
    render(<ClonedToBanner workspaceSlug="dimagi-team" slug="spark-facilitator" runId="r" />);
    expect(await screen.findByText(/do not reach the copy/)).toBeTruthy();
    expect(screen.queryByText("x")).toBeNull();
  });
});
