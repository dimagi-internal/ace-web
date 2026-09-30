import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import UnscopedOppLinkPage from "../UnscopedOppLinkPage";

describe("UnscopedOppLinkPage", () => {
  it("says the link has no workspace and points at the opp list, without guessing one", () => {
    render(
      <MemoryRouter initialEntries={["/opps/spark-facilitator"]}>
        <Routes>
          <Route path="/opps/:slug" element={<UnscopedOppLinkPage />} />
          <Route path="/w/*" element={<div>workspace page</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText(/doesn't say which workspace/)).toBeInTheDocument();
    expect(screen.getByText(/\/w\/<workspace>\/opps\/spark-facilitator/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to your opps" })).toHaveAttribute("href", "/opps");
    expect(screen.queryByText("workspace page")).not.toBeInTheDocument();
  });
});
