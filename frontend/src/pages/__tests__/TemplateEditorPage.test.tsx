import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import * as api from "@/api/videos";
import type { ProgramSpec } from "@/components/videos/types";
import TemplateEditorPage from "@/pages/TemplateEditorPage";

const MOCK_BUNDLE: api.TemplateBundle = {
  meta: {
    id: "tmpl-1",
    name: "FLW Onboarding",
    description: "Standard onboarding for frontline workers",
    intent: "Get new frontline workers up to speed on the program and app.",
    intended_audience: "New frontline workers",
    when_to_use: "When onboarding new hires",
  },
  skeleton_yaml: "beats:\n  - id: hook\n    seconds: 8",
  prompt_md: "# Generate a training video\n\nDetails here.",
};

const MOCK_EXAMPLE: api.TemplateExampleOut = {
  template_id: "tmpl-1",
  example_yaml: "beats:\n  - id: hook\n    seconds: 8\n  - id: intro\n    seconds: 6",
};

// A minimal parsed spec that the BeatEditor can render.
const MOCK_EXAMPLE_SPEC: ProgramSpec = {
  slug: "tmpl-1",
  name: "FLW Onboarding Example",
  narration: { by_beat: { hook: "Welcome to the program" } },
  beats: [
    { id: "hook", kind: "intro_hook", seconds: 8 },
    { id: "intro", kind: "intro_handoff", seconds: 6 },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/w/ws/videos/templates/tmpl-1"]}>
      <Routes>
        <Route
          path="/w/:workspaceSlug/videos/templates/:templateId"
          element={<TemplateEditorPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TemplateEditorPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getVideoTemplate").mockResolvedValue(MOCK_BUNDLE);
    vi.spyOn(api, "getTemplateExample").mockResolvedValue(MOCK_EXAMPLE);
    vi.spyOn(api, "patchTemplate").mockResolvedValue(MOCK_BUNDLE);
    // Default: no parsed example spec — falls back to YAML textarea.
    vi.spyOn(api, "getTemplateExampleSpec").mockRejectedValue(new Error("not found"));
  });

  it("renders the Metadata section heading", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding"); // wait for load
    // There are multiple elements matching /metadata/i — assert at least one h2
    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings.some((h) => /metadata/i.test(h.textContent ?? ""))).toBe(true);
  });

  it("does NOT render a Generate prompt section (removed — generator uses Intent)", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    expect(screen.queryByText(/generate prompt/i)).not.toBeInTheDocument();
  });

  it("renders the Skeleton section heading", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    // "Skeleton" appears in the h2 heading and in the panel label — assert the h2
    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings.some((h) => /^skeleton$/i.test(h.textContent?.trim() ?? ""))).toBe(true);
  });

  it("renders the Demo / example section heading", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    expect(screen.getByText(/demo.*example|example.*demo/i)).toBeInTheDocument();
  });

  it("populates the name field from loaded meta", async () => {
    renderPage();
    const nameInput = await screen.findByLabelText(/^name$/i);
    expect(nameInput).toHaveValue("FLW Onboarding");
  });

  it("populates the skeleton textarea with skeleton_yaml", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    const skeletonTextarea = screen.getByLabelText(/skeleton yaml/i);
    expect(skeletonTextarea).toHaveValue(MOCK_BUNDLE.skeleton_yaml);
  });

  it("populates the example textarea with example_yaml (fallback when no parsed spec)", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    const exampleTextarea = screen.getByLabelText(/example yaml/i);
    expect(exampleTextarea).toHaveValue(MOCK_EXAMPLE.example_yaml);
  });

  it("Save button is disabled when not dirty", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    expect(saveBtn).toBeDisabled();
  });

  it("editing a meta field enables Save", async () => {
    renderPage();
    const nameInput = await screen.findByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: "new" } });
    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    expect(saveBtn).not.toBeDisabled();
  });

  it("clicking Save calls patchTemplate once with the coalesced patch", async () => {
    renderPage();
    const nameInput = await screen.findByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: "new" } });

    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(api.patchTemplate).toHaveBeenCalledTimes(1);
    });

    const [ws, id, body] = (api.patchTemplate as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(ws).toBe("ws");
    expect(id).toBe("tmpl-1");
    expect(body).toMatchObject({ meta: { name: "new" } });
  });

  it("Save button returns to disabled after a successful save", async () => {
    vi.spyOn(api, "patchTemplate").mockResolvedValue(MOCK_BUNDLE);
    vi.spyOn(api, "getTemplateExample").mockResolvedValue(MOCK_EXAMPLE);

    renderPage();
    const nameInput = await screen.findByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: "new" } });

    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(saveBtn).toBeDisabled();
    });
  });
});

// ── BeatEditor integration tests ─────────────────────────────────────────────
// When getTemplateExampleSpec returns a parsed spec, TemplateEditorPage mounts
// BeatEditor instead of the YAML textarea as the primary example editor.

describe("TemplateEditorPage — BeatEditor for example spec", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getVideoTemplate").mockResolvedValue(MOCK_BUNDLE);
    vi.spyOn(api, "getTemplateExample").mockResolvedValue(MOCK_EXAMPLE);
    vi.spyOn(api, "patchTemplate").mockResolvedValue(MOCK_BUNDLE);
    vi.spyOn(api, "getTemplateExampleSpec").mockResolvedValue({
      template_id: "tmpl-1",
      spec: MOCK_EXAMPLE_SPEC,
    });
  });

  it("renders beats from the example spec in the BeatEditor", async () => {
    renderPage();
    // Wait for load — the template name appears in the heading
    await screen.findByText("FLW Onboarding");
    // The narration widget for the 'hook' beat renders the narration text.
    expect(screen.getByText("Welcome to the program")).toBeInTheDocument();
  });

  it("does NOT render the YAML textarea when BeatEditor is mounted", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    // The YAML textarea has aria-label "Example YAML" — should not be in DOM.
    expect(screen.queryByLabelText(/example yaml/i)).not.toBeInTheDocument();
  });

  it("Raw YAML toggle shows the YAML textarea", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    // Click "Raw YAML" toggle button
    fireEvent.click(screen.getByRole("button", { name: /raw yaml/i }));
    // Now the YAML textarea should appear
    expect(screen.getByLabelText(/example yaml/i)).toBeInTheDocument();
  });

  it("BeatEditor onSave calls patchTemplate with example_spec object", async () => {
    vi.spyOn(api, "submitEditBatch").mockResolvedValue({ ok: true, applied: 1, message: "ok" });

    renderPage();
    await screen.findByText("FLW Onboarding");

    // Make an edit: click on the narration widget to open the drawer.
    fireEvent.click(screen.getByText("Welcome to the program"));
    // Target the textarea within the dialog (the page has many other textboxes).
    const dialog = await screen.findByRole("dialog");
    const ta = within(dialog).getByRole("textbox");
    fireEvent.change(ta, { target: { value: "Updated narration" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Done/i }));

    // BeatEditor's TopBar should show the pending edit count.
    expect(screen.getByText(/1 edit pending/i)).toBeInTheDocument();

    // Click "Save changes" in the BeatEditor TopBar.
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));

    // patchTemplate should be called with example_spec (not example_yaml).
    await waitFor(() => expect(api.patchTemplate).toHaveBeenCalled());
    const calls = (api.patchTemplate as ReturnType<typeof vi.fn>).mock.calls;
    // Find the call that carries example_spec
    const specCall = calls.find(([, , body]) => body?.example_spec != null);
    expect(specCall).toBeTruthy();
    const [ws, id, body] = specCall!;
    expect(ws).toBe("ws");
    expect(id).toBe("tmpl-1");
    // The saved spec should carry the updated narration
    expect(body.example_spec?.narration?.by_beat?.hook).toBe("Updated narration");
    // submitEditBatch must NOT have been called (onSave override path)
    expect(api.submitEditBatch).not.toHaveBeenCalled();
  });

  it("BeatEditor onSave shows saved confirmation after successful patch", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");

    // Make an edit: click on the narration widget to open the drawer.
    fireEvent.click(screen.getByText("Welcome to the program"));
    const dialog = await screen.findByRole("dialog");
    const ta = within(dialog).getByRole("textbox");
    fireEvent.change(ta, { target: { value: "Changed" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Done/i }));

    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() => {
      expect(screen.getByText(/Saved at/i)).toBeInTheDocument();
    });
  });
});
