import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { VIEW_KINDS } from "@/components/views/ViewSwitcher";
import { useViewMode } from "@/hooks/useViewMode";

function Probe() {
  const { view } = useViewMode("phase");
  return <span data-testid="view">{view}</span>;
}

function renderAt(search: string) {
  return render(
    <MemoryRouter initialEntries={[`/w/ws1/opps/o${search}`]}>
      <Routes>
        <Route path="/w/:workspaceSlug/opps/:slug" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("useViewMode", () => {
  it.each(VIEW_KINDS)("round-trips ?view=%s from the URL", (kind) => {
    renderAt(`?view=${kind}`);
    expect(screen.getByTestId("view")).toHaveTextContent(kind);
  });

  it("every declared view kind survives a reload", () => {
    // The regression this guards: `review` was added to the type but not to
    // the runtime list, so the tab set ?view=review and the next read threw
    // it away — a shared link to that tab silently opened somewhere else.
    for (const kind of VIEW_KINDS) {
      const { unmount } = renderAt(`?view=${kind}`);
      expect(screen.getByTestId("view")).toHaveTextContent(kind);
      unmount();
    }
  });

  it("falls back to the default for a kind that isn't real", () => {
    renderAt("?view=not-a-view");
    expect(screen.getByTestId("view")).toHaveTextContent("phase");
  });

  it("uses the default when no view is named", () => {
    renderAt("");
    expect(screen.getByTestId("view")).toHaveTextContent("phase");
  });
});
