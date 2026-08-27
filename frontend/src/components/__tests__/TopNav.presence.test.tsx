import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The binding invariant of this surface: presence must never break a page.
 *
 * `PresenceHeaderBadge` calls `pageKeyFor` DURING RENDER, and TopNav is
 * mounted above the router's `<Outlet/>` (App.tsx) in an SPA that defines
 * no `errorElement` anywhere (router.tsx). So anything a route rule throws
 * takes down the whole app — blank screen, no nav to escape with — rather
 * than letting the routed page render its own not-found.
 *
 * Two layers are covered here, and both must hold independently:
 *   1. the real rules survive a malformed percent-escape (`safeDecode` in
 *      presence/routes.ts);
 *   2. even a rule that throws for some UNANTICIPATED reason is contained
 *      (`resolvePresenceLocation`'s try/catch in TopNav).
 */

const mocks = vi.hoisted(() => ({
  usePresence: vi.fn(() => ({ viewers: [] })),
  // Null = "delegate to the real pageKeyFor"; a function = use it instead.
  pageKeyForOverride: null as null | (() => never),
}));

vi.mock("canopy-ui/presence", async (importOriginal) => {
  const actual = await importOriginal<typeof import("canopy-ui/presence")>();
  return {
    ...actual,
    // Stubbed so the badge never opens a real WebSocket in jsdom; the
    // roster itself is not what these tests are about.
    usePresence: mocks.usePresence,
    pageKeyFor: (...args: Parameters<typeof actual.pageKeyFor>) =>
      mocks.pageKeyForOverride ? mocks.pageKeyForOverride() : actual.pageKeyFor(...args),
    PresenceBadge: () => <div data-testid="presence-badge" />,
  };
});

vi.mock("@/components/WorkspaceSwitcher", () => ({ WorkspaceSwitcher: () => <div /> }));
vi.mock("@/components/UserMenu", () => ({ UserMenu: () => <div /> }));
vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => ({
    current: { slug: "ws", display_name: "WS" },
    all: [{ slug: "ws", display_name: "WS" }],
    loading: false,
    error: null,
    reload: () => {},
  }),
}));

import { TopNav } from "../TopNav";

function renderAt(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Routes>
        <Route path="*" element={<TopNav />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TopNav presence badge — never takes the app down", () => {
  beforeEach(() => {
    mocks.usePresence.mockClear();
    mocks.pageKeyForOverride = null;
  });

  it("renders a malformed-percent-escape URL instead of blanking the app", () => {
    // Real rules, real pageKeyFor: this is the reported crash path — a
    // pasted or truncated step URL where `decodeURIComponent("100%")`
    // raises `URIError: URI malformed`.
    renderAt("/w/ws/opps/o/runs/r/steps/100%");

    expect(screen.getByText("ACE")).toBeInTheDocument();
    expect(screen.getByTestId("presence-badge")).toBeInTheDocument();
    // The badge still joins the run's roster — the raw segment is used as
    // the sub-location label rather than the whole location being dropped.
    expect(mocks.usePresence).toHaveBeenCalledWith(
      expect.objectContaining({
        location: { pageKey: "ace:ws:opp:o/r", subLocation: "100%" },
      }),
    );
  });

  it("contains a route rule that throws for any other reason", () => {
    mocks.pageKeyForOverride = () => {
      throw new URIError("URI malformed");
    };

    renderAt("/w/ws/opps");

    // The nav — and therefore everything below the Outlet — still renders.
    expect(screen.getByText("ACE")).toBeInTheDocument();
    // ...and presence degrades to "no location", not to a crash.
    expect(mocks.usePresence).toHaveBeenCalledWith(expect.objectContaining({ location: null }));
  });
});
