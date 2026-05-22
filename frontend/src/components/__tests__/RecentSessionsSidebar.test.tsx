import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { RecentSessionsSidebar } from "../RecentSessionsSidebar";
import type { Session } from "../../api/types.ws";

/**
 * Issue #527: stronger visual grouping in the chat-session sidebar.
 * The sidebar groups sessions by opp_slug. We assert the structural
 * pieces the design hangs on:
 *
 *   - One wrapper per group (`[data-testid="opp-group"]`)
 *   - A divider class on every group except the first (so adjacent
 *     groups visually separate, but the top of the list doesn't get
 *     a redundant rule that fights the "New Chat" button above it)
 *   - A per-row colored accent bar (`[data-testid="opp-accent-bar"]`)
 *     for linked opps, and no accent bar for the unlinked "Other
 *     chats" bucket so it stays recognizable as an end-of-list state
 */

function buildSession(overrides: Partial<Session>): Session {
  return {
    slug: "sess-x",
    title: "Untitled",
    status: "active",
    backend_kind: "cli",
    source: "web",
    cli_session_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    message_count: 0,
    preview: "",
    opp_slug: "",
    opp_run_id: "",
    opp_step_skill: "",
    opp_display_name: "",
    opp_step_skill_display: "",
    ...overrides,
  };
}

const SESSIONS: Session[] = [
  buildSession({
    slug: "sess-malaria-1",
    title: "Pricing brief",
    opp_slug: "MALARIA-ITN-APP",
    opp_display_name: "Malaria ITN App",
  }),
  buildSession({
    slug: "sess-malaria-2",
    title: "FGD prep",
    opp_slug: "MALARIA-ITN-APP",
    opp_display_name: "Malaria ITN App",
  }),
  buildSession({
    slug: "sess-leep-1",
    title: "Color sampling",
    opp_slug: "LEEP-PAINT-COLLECTION",
    opp_display_name: "Leep Paint Collection",
  }),
  // Unlinked / "Other chats" group — last by convention.
  buildSession({
    slug: "sess-loose-1",
    title: "Scratch pad",
    opp_slug: "",
    opp_display_name: "",
  }),
];

vi.mock("../../hooks/useRecentSessions", async () => {
  const actual = await vi.importActual<
    typeof import("../../hooks/useRecentSessions")
  >("../../hooks/useRecentSessions");
  return {
    ...actual,
    useRecentSessions: () => ({
      sessions: SESSIONS,
      loading: false,
      refresh: vi.fn(),
    }),
  };
});

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/w/ws-1/chat/sess-malaria-1"]}>
      <Routes>
        <Route
          path="/w/:workspaceSlug/chat/:slug"
          element={<RecentSessionsSidebar currentSlug="sess-malaria-1" />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RecentSessionsSidebar — visual grouping (issue #527)", () => {
  it("renders one opp-group wrapper per unique opp_slug, unlinked last", () => {
    renderSidebar();
    const groups = screen.getAllByTestId("opp-group");
    // 3 distinct opps in the fixture: two linked + the unlinked bucket.
    expect(groups).toHaveLength(3);
    expect(groups[0].getAttribute("data-opp-slug")).toBe("MALARIA-ITN-APP");
    expect(groups[1].getAttribute("data-opp-slug")).toBe(
      "LEEP-PAINT-COLLECTION",
    );
    // The unlinked bucket is always last regardless of recency.
    expect(groups[2].getAttribute("data-opp-slug")).toBe("");
  });

  it("draws a divider above every group except the first", () => {
    renderSidebar();
    const groups = screen.getAllByTestId("opp-group");
    // First group: no top border — it sits directly under the "New Chat" button.
    expect(groups[0].className).not.toMatch(/border-t/);
    // Every subsequent group: subtle 1px divider.
    for (const g of groups.slice(1)) {
      expect(g.className).toMatch(/border-t/);
    }
  });

  it("renders a colored accent bar on each row of a linked opp group", () => {
    renderSidebar();
    const linkedGroup = screen.getAllByTestId("opp-group")[0];
    const bars = within(linkedGroup).getAllByTestId("opp-accent-bar");
    // Two MALARIA sessions in the fixture; each gets its own bar.
    expect(bars).toHaveLength(2);
    // Same opp_slug → same accent color. (We don't pin the literal HSL
    // value here so we don't break if the hash impl rebalances; we
    // just need consistency within a group.)
    // jsdom normalizes hsl(...) to rgb(...) on read, so we just check
    // that a color is set and the two rows share it.
    const colors = bars.map((b) => (b as HTMLElement).style.backgroundColor);
    expect(new Set(colors).size).toBe(1);
    expect(colors[0]).not.toBe("");
  });

  it("uses a different accent color for a different opp_slug", () => {
    renderSidebar();
    const [g1, g2] = screen.getAllByTestId("opp-group");
    const c1 = (
      within(g1).getAllByTestId("opp-accent-bar")[0] as HTMLElement
    ).style.backgroundColor;
    const c2 = (
      within(g2).getAllByTestId("opp-accent-bar")[0] as HTMLElement
    ).style.backgroundColor;
    expect(c1).not.toBe(c2);
  });

  it("does NOT render accent bars on the unlinked 'Other chats' group", () => {
    renderSidebar();
    const groups = screen.getAllByTestId("opp-group");
    const unlinked = groups[groups.length - 1];
    expect(within(unlinked).queryByTestId("opp-accent-bar")).toBeNull();
    // Header still renders, with "Other chats" label.
    expect(within(unlinked).getByText(/other chats/i)).toBeInTheDocument();
  });
});
