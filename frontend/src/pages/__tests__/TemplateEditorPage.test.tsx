import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import * as api from "@/api/videos";
import TemplateEditorPage from "@/pages/TemplateEditorPage";

const MOCK_BUNDLE: api.TemplateBundle = {
  meta: {
    id: "tmpl-1",
    name: "FLW Onboarding",
    description: "Standard onboarding for frontline workers",
    expected_duration_seconds: 57,
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
  });

  it("renders the Metadata section heading", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding"); // wait for load
    // There are multiple elements matching /metadata/i — assert at least one h2
    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings.some((h) => /metadata/i.test(h.textContent ?? ""))).toBe(true);
  });

  it("renders the Generate prompt section heading", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    expect(screen.getByText(/generate prompt/i)).toBeInTheDocument();
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

  it("populates the prompt textarea with prompt_md", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    const promptTextarea = screen.getByLabelText(/^prompt$/i);
    expect(promptTextarea).toHaveValue(MOCK_BUNDLE.prompt_md);
  });

  it("populates the skeleton textarea with skeleton_yaml", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    const skeletonTextarea = screen.getByLabelText(/skeleton yaml/i);
    expect(skeletonTextarea).toHaveValue(MOCK_BUNDLE.skeleton_yaml);
  });

  it("populates the example textarea with example_yaml", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    const exampleTextarea = screen.getByLabelText(/example yaml/i);
    expect(exampleTextarea).toHaveValue(MOCK_EXAMPLE.example_yaml);
  });

  it("Save button is disabled when not dirty", async () => {
    renderPage();
    await screen.findByText("FLW Onboarding");
    const saveBtn = screen.getByRole("button", { name: /save/i });
    expect(saveBtn).toBeDisabled();
  });

  it("editing a meta field enables Save", async () => {
    renderPage();
    const nameInput = await screen.findByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: "new" } });
    const saveBtn = screen.getByRole("button", { name: /save/i });
    expect(saveBtn).not.toBeDisabled();
  });

  it("clicking Save calls patchTemplate once with the coalesced patch", async () => {
    renderPage();
    const nameInput = await screen.findByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: "new" } });

    const saveBtn = screen.getByRole("button", { name: /save/i });
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

    const saveBtn = screen.getByRole("button", { name: /save/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(saveBtn).toBeDisabled();
    });
  });
});
