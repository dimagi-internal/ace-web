import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WorkbenchLayout } from "../WorkbenchLayout";

describe("WorkbenchLayout", () => {
  it("renders header, toolbar and center", () => {
    render(
      <WorkbenchLayout
        header={<div>HEADER</div>}
        toolbar={<div>TABS</div>}
        center={<div>CENTER</div>}
      />,
    );
    expect(screen.getByText("HEADER")).toBeInTheDocument();
    expect(screen.getByText("TABS")).toBeInTheDocument();
    expect(screen.getByText("CENTER")).toBeInTheDocument();
  });

  it("renders left and right rails when provided", () => {
    render(
      <WorkbenchLayout
        center={<div>CENTER</div>}
        left={{ title: "Nav", collapsed: false, onToggle: () => {}, content: <div>LEFT</div> }}
        right={{ title: "Inspector", collapsed: false, onToggle: () => {}, content: <div>RIGHT</div> }}
      />,
    );
    expect(screen.getByText("LEFT")).toBeInTheDocument();
    expect(screen.getByText("RIGHT")).toBeInTheDocument();
    expect(screen.getByText("Nav")).toBeInTheDocument();
    expect(screen.getByText("Inspector")).toBeInTheDocument();
  });

  it("omits rails that are not provided", () => {
    render(<WorkbenchLayout center={<div>CENTER</div>} />);
    expect(screen.queryByText("LEFT")).not.toBeInTheDocument();
    expect(screen.queryByText("RIGHT")).not.toBeInTheDocument();
  });
});
