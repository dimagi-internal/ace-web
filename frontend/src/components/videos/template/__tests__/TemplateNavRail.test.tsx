import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { TemplateNavRail } from "../TemplateNavRail";

const TEMPLATES = [
  { id: "connect-explainer", name: "Connect Explainer" },
  { id: "flw-onboarding", name: "FLW Onboarding" },
];

const BEATS = [
  { id: "hook", kind: "intro_hook", seconds: 8 },
  { id: "problem", kind: "headline_stat", seconds: 10 },
  { id: "cta", kind: "end_card", seconds: 5 },
];

function renderRail(overrides: Partial<Parameters<typeof TemplateNavRail>[0]> = {}) {
  return render(
    <MemoryRouter>
      <TemplateNavRail
        workspaceSlug="ws"
        templates={TEMPLATES}
        currentTemplateId="flw-onboarding"
        hasExample={true}
        beats={BEATS}
        {...overrides}
      />
    </MemoryRouter>,
  );
}

describe("TemplateNavRail", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders all template names", () => {
    renderRail();
    expect(screen.getByText("Connect Explainer")).toBeInTheDocument();
    expect(screen.getByText("FLW Onboarding")).toBeInTheDocument();
  });

  it("highlights the current template", () => {
    renderRail();
    // The current template name button has font-medium. There are two buttons
    // whose accessible name contains "FLW Onboarding" (name + expand/collapse),
    // so we grab all and check at least one is font-medium.
    const btns = screen.getAllByRole("button", { name: /FLW Onboarding/ });
    expect(btns.some((b) => /font-medium/.test(b.className))).toBe(true);
  });

  it("renders the 3 section labels for the current template", () => {
    renderRail();
    expect(screen.getByText("Metadata")).toBeInTheDocument();
    expect(screen.getByText("Skeleton")).toBeInTheDocument();
    expect(screen.getByText("Demo / example")).toBeInTheDocument();
    // Generate prompt was removed — the generator works from Intent + Skeleton + example.
    expect(screen.queryByText("Generate prompt")).not.toBeInTheDocument();
  });

  it("renders beat labels under Demo when hasExample and beats are provided", () => {
    renderRail();
    // sectionLabel("hook").name = "Opening tagline"
    expect(screen.getByText("Opening tagline")).toBeInTheDocument();
    // sectionLabel("problem").name = "Headline stat"
    expect(screen.getByText("Headline stat")).toBeInTheDocument();
    // sectionLabel("cta").name = "End card"
    expect(screen.getByText("End card")).toBeInTheDocument();
  });

  it("shows 'No demo' hint when hasExample is false", () => {
    renderRail({ hasExample: false, beats: [] });
    expect(screen.getByText(/no demo/i)).toBeInTheDocument();
    // Beats should NOT be rendered
    expect(screen.queryByText("Opening tagline")).not.toBeInTheDocument();
  });

  it("shows 'No demo' hint when hasExample is true but beats is empty", () => {
    renderRail({ hasExample: true, beats: [] });
    expect(screen.getByText(/no demo/i)).toBeInTheDocument();
  });

  it("clicking a section label calls scrollIntoView", () => {
    const mockScrollIntoView = vi.fn();
    const mockGetElementById = vi.spyOn(document, "getElementById").mockReturnValue({
      scrollIntoView: mockScrollIntoView,
    } as unknown as HTMLElement);

    renderRail();
    fireEvent.click(screen.getByText("Metadata"));

    expect(mockGetElementById).toHaveBeenCalledWith("tpl-section-metadata");
    expect(mockScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });

    mockGetElementById.mockRestore();
  });

  it("clicking Skeleton calls scrollIntoView with tpl-section-skeleton", () => {
    const mockScrollIntoView = vi.fn();
    const mockGetElementById = vi.spyOn(document, "getElementById").mockReturnValue({
      scrollIntoView: mockScrollIntoView,
    } as unknown as HTMLElement);

    renderRail();
    fireEvent.click(screen.getByText("Skeleton"));

    expect(mockGetElementById).toHaveBeenCalledWith("tpl-section-skeleton");
    expect(mockScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });

    mockGetElementById.mockRestore();
  });

  it("clicking a beat label calls scrollToBeat (scrollIntoView with beat-<id>)", () => {
    const mockScrollIntoView = vi.fn();
    const mockGetElementById = vi.spyOn(document, "getElementById").mockReturnValue({
      scrollIntoView: mockScrollIntoView,
    } as unknown as HTMLElement);

    renderRail();
    fireEvent.click(screen.getByText("Opening tagline")); // beat id = "hook"

    expect(mockGetElementById).toHaveBeenCalledWith("beat-hook");
    expect(mockScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });

    mockGetElementById.mockRestore();
  });

  it("non-current templates do not show sections", () => {
    renderRail();
    // Connect Explainer is NOT current — its sections should not be visible.
    // The sections (Metadata, etc.) belong only to the current template.
    // We confirm sections exist only once (not doubled):
    expect(screen.getAllByText("Metadata")).toHaveLength(1);
  });

  it("renders loading state when templates is null", () => {
    renderRail({ templates: null });
    // Should show skeleton placeholders (no template names visible)
    expect(screen.queryByText("Connect Explainer")).not.toBeInTheDocument();
  });

  it("renders 'No templates' message when templates is empty array", () => {
    renderRail({ templates: [] });
    expect(screen.getByText(/no templates/i)).toBeInTheDocument();
  });
});
