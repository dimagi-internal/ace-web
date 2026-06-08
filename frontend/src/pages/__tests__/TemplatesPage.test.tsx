import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import * as api from "@/api/videos";
import TemplatesPage from "@/pages/TemplatesPage";

describe("TemplatesPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "listVideoTemplates").mockResolvedValue([
      {
        id: "tmpl-1",
        name: "FLW Onboarding",
        description: "Standard onboarding for frontline workers",
        expected_duration_seconds: 57,
        intended_audience: "New frontline workers",
        when_to_use: "When onboarding new hires",
      },
      {
        id: "tmpl-2",
        name: "Product Demo",
        description: "Showcase a product feature",
        expected_duration_seconds: 90,
        intended_audience: "Program managers",
        when_to_use: "During quarterly reviews",
      },
      {
        id: "tmpl-3",
        name: "CHW Training",
        description: "Community health worker training module",
        expected_duration_seconds: 120,
        intended_audience: "Community health workers",
        when_to_use: "Annual refresher training",
      },
    ]);
  });

  it("renders all three template names", async () => {
    render(
      <MemoryRouter initialEntries={["/w/ws/videos/templates"]}>
        <Routes>
          <Route path="/w/:workspaceSlug/videos/templates" element={<TemplatesPage />} />
        </Routes>
      </MemoryRouter>,
    );
    // Template names appear in both the rail and the card grid — use findAllByText
    const flwItems = await screen.findAllByText("FLW Onboarding");
    expect(flwItems.length).toBeGreaterThanOrEqual(1);
    const demoItems = await screen.findAllByText("Product Demo");
    expect(demoItems.length).toBeGreaterThanOrEqual(1);
    const chwItems = await screen.findAllByText("CHW Training");
    expect(chwItems.length).toBeGreaterThanOrEqual(1);
  });

  it("each template has an Edit link pointing at videos/templates/{id}", async () => {
    render(
      <MemoryRouter initialEntries={["/w/ws/videos/templates"]}>
        <Routes>
          <Route path="/w/:workspaceSlug/videos/templates" element={<TemplatesPage />} />
        </Routes>
      </MemoryRouter>,
    );
    // Wait for data to load — names appear at least once in the card grid
    await screen.findAllByText("FLW Onboarding");

    const editLinks = screen.getAllByRole("link", { name: /edit/i });
    expect(editLinks).toHaveLength(3);

    const hrefs = editLinks.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/w/ws/videos/templates/tmpl-1");
    expect(hrefs).toContain("/w/ws/videos/templates/tmpl-2");
    expect(hrefs).toContain("/w/ws/videos/templates/tmpl-3");
  });
});
