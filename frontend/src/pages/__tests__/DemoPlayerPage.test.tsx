import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DemoPayload } from "@/api/demo";
import { SAMPLE } from "@/components/demo/__fixtures__/sample";

const fetchDemoPayload = vi.fn();
vi.mock("@/api/demo", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/demo")>()),
  fetchDemoPayload: (...args: unknown[]) => fetchDemoPayload(...args),
}));

const { default: DemoPlayerPage } = await import("../DemoPlayerPage");

function renderAt(search = "") {
  return render(
    <MemoryRouter
      initialEntries={[`/w/ws1/opps/hh-poverty-targeting/runs/20260722-1341/demo${search}`]}
    >
      <Routes>
        <Route
          path="/w/:workspaceSlug/opps/:slug/runs/:runId/demo"
          element={<DemoPlayerPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DemoPlayerPage", () => {
  beforeEach(() => {
    fetchDemoPayload.mockReset();
    fetchDemoPayload.mockResolvedValue(SAMPLE);
  });

  it("names the run and lists every act", async () => {
    renderAt();
    expect(await screen.findByText("Household poverty targeting")).toBeInTheDocument();
    expect(screen.getByText("20260722-1341")).toBeInTheDocument();
    for (const title of ["The run", "Where the time went", "What it caught", "What it decided"]) {
      expect(screen.getByRole("button", { name: new RegExp(title) })).toBeInTheDocument();
    }
  });

  it("opens on the timeline with the run paused at zero", async () => {
    renderAt();
    expect(await screen.findByText("Press space to start the run.")).toBeInTheDocument();
    // Both counters start at zero. The run clock pads to hours because this
    // run is long, so the two read differently by design.
    expect(screen.getByText("0:00:00")).toBeInTheDocument();
    expect(screen.getByText("0:00")).toBeInTheDocument();
  });

  it("shows the act named in the URL", async () => {
    renderAt("?act=gates");
    expect(await screen.findByText(/stopped by its own review/i)).toBeInTheDocument();
    expect(screen.getByText(/Deliver form asks visit outcome/)).toBeInTheDocument();
  });

  it("renders the time ledger in wall time, never tokens or cost", async () => {
    const { container } = renderAt("?act=time_ledger");
    await screen.findByText("Start to finish, unattended");
    const text = container.textContent?.toLowerCase() ?? "";
    for (const banned of ["token", "cost", "usd", "$"]) {
      expect(text).not.toContain(banned);
    }
  });

  it("leads the decisions act with the rows a person changed", async () => {
    renderAt("?act=decisions");
    expect(await screen.findByText("Changed by a person")).toBeInTheDocument();
    expect(screen.getByText("Which programme archetype fits this design?")).toBeInTheDocument();
    expect(screen.getByText("Service delivery")).toBeInTheDocument();
  });

  it("explains an unavailable act instead of rendering an empty stage", async () => {
    const thin: DemoPayload = {
      ...SAMPLE,
      capabilities: { ...SAMPLE.capabilities, gates: false },
      acts: SAMPLE.acts.map((act) =>
        act.id === "gates"
          ? {
              ...act,
              available: false,
              unavailable_reason: "No step in this run failed its own QA or judge.",
            }
          : act,
      ),
    };
    fetchDemoPayload.mockResolvedValue(thin);
    renderAt("?act=gates");
    expect(
      await screen.findByText("No step in this run failed its own QA or judge."),
    ).toBeInTheDocument();
  });

  it("says what to do when the run can't be loaded", async () => {
    fetchDemoPayload.mockRejectedValue(new Error("Couldn't load this run (404)."));
    renderAt();
    await waitFor(() =>
      expect(screen.getByText("Couldn't load this run (404).")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Sign in and check you're a member/)).toBeInTheDocument();
  });
});
