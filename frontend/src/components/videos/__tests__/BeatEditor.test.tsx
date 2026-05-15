import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BeatEditor } from "../BeatEditor";
import type { ProgramSpec } from "../types";
import * as api from "@/api/videos";

const spec: ProgramSpec = {
  slug: "demo", name: "Demo",
  narration: { by_beat: { hook: "Initial" } },
  beats: [
    { id: "hook", kind: "intro_hook", seconds: 4 },
  ],
};

describe("BeatEditor integration", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("edit → save flow clears buffer", async () => {
    const submit = vi.spyOn(api, "submitEditBatch").mockResolvedValue({
      ok: true, applied: 1, message: "ok",
    });
    vi.spyOn(api, "getVideoRun").mockResolvedValue({
      program_slug: "demo", run_id: "run-001", name: "Demo",
      manifest_count: 0, has_output: false, has_explorer_build: false,
      explorer_url: "", yaml_path: "",
      spec: { ...spec, narration: { by_beat: { hook: "Updated" } } },
    } as any);

    render(
      <BeatEditor
        workspaceSlug="ws1" programSlug="demo" runId="run-001" spec={spec}
      />,
    );

    // Click narration widget → drawer opens
    fireEvent.click(screen.getByText(/Initial/));
    const ta = await screen.findByRole("textbox");
    fireEvent.change(ta, { target: { value: "Updated" } });
    fireEvent.click(screen.getByRole("button", { name: /Done/i }));

    // TopBar shows 1 pending
    expect(screen.getByText(/1 edit pending/i)).toBeInTheDocument();

    // Save
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));
    await waitFor(() => expect(submit).toHaveBeenCalled());
    const args = submit.mock.calls[0];
    expect(args[0]).toBe("ws1");
    expect(args[1]).toBe("demo");
    expect(args[3]).toEqual([
      { op: "set-narration", beatId: "hook", text: "Updated" },
    ]);

    // Saved label appears
    await waitFor(() => expect(screen.getByText(/Saved at/i)).toBeInTheDocument());
  });
});
