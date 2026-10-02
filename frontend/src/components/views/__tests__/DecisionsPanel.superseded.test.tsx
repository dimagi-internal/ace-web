/**
 * Superseded rows are history, not live choices (ace-web#848, ACE #2595).
 *
 * A row carrying `superseded_by` — an in-run correction, or a row a fork
 * retired under a renamed id — used to render on the Phases decisions panel as
 * one more live choice, so a corrected question appeared twice with two
 * answers. It must instead fold under the row that replaced it as an earlier
 * version, reachable but collapsed. The public summary already drops them.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Decision } from "@/api/types.ws";
import { splitSuperseded } from "../decisions/supersession";
import { DecisionsPanel } from "../DecisionsPanel";

function dec(over: Partial<Decision> = {}): Decision {
  return {
    id: "row",
    phase: "design",
    phase_raw: "1-design",
    skill: "idea-to-pdd",
    question: "Which archetype?",
    ai_default: "service delivery",
    override: "",
    options_considered: [],
    source: "",
    status: "ai-default",
    notes: "",
    override_reasoning: "",
    evidence_basis: "stated",
    conflict_signals: [],
    ...over,
  };
}

// An in-run correction chain (v1 → v2 → live), a fork-retired row whose
// successor is live, a retired row whose phase has not re-run (no live
// successor), and a plain live row with no history.
const ROWS: Decision[] = [
  dec({ id: "arch-v1", ai_default: "data collection", superseded_by: "arch-v2" }),
  dec({ id: "arch-v2", ai_default: "survey", superseded_by: "arch" }),
  dec({ id: "arch", ai_default: "service delivery" }),
  dec({ id: "pay-20260930-1200", question: "Payment per visit?", ai_default: "2 USD", superseded_by: "pay" }),
  dec({ id: "pay", question: "Payment per visit?", ai_default: "3 USD" }),
  dec({ id: "gps-20260930-1200", question: "Capture GPS?", ai_default: "yes", superseded_by: "gps" }),
  dec({ id: "lang", question: "Language?", ai_default: "English" }),
];

const openPanel = () => fireEvent.click(screen.getByText("Decisions").closest("button")!);
const rowFor = (question: string) => screen.getByText(question).closest("li")!;

describe("DecisionsPanel — superseded rows", () => {
  it("lists only the live choices, and counts only them", () => {
    render(<DecisionsPanel phase="design" decisions={ROWS} />);
    openPanel();
    // One row per live decision: no second "Which archetype?" / "Payment per visit?".
    expect(screen.getAllByText("Which archetype?")).toHaveLength(1);
    expect(screen.getAllByText("Payment per visit?")).toHaveLength(1);
    expect(screen.queryByText("Capture GPS?")).toBeNull();
    const header = screen.getByText("Decisions").closest("button")!;
    expect(within(header).getByText("3")).toBeInTheDocument();
  });

  it("shows a live row WITH history as live (negative control), marked revised", () => {
    render(<DecisionsPanel phase="design" decisions={ROWS} />);
    openPanel();
    const arch = rowFor("Which archetype?");
    expect(within(arch).getByText("service delivery")).toBeInTheDocument();
    expect(within(arch).getByText("revised")).toBeInTheDocument();
    // …and a live row without history carries no such mark.
    expect(within(rowFor("Language?")).queryByText("revised")).toBeNull();
  });

  it("keeps the earlier versions reachable, collapsed, under the live row — nearest first", () => {
    render(<DecisionsPanel phase="design" decisions={ROWS} />);
    openPanel();
    fireEvent.click(screen.getByText("Which archetype?"));
    const toggle = screen.getByRole("button", { name: "2 earlier versions in this run" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("survey")).toBeNull();
    fireEvent.click(toggle);
    const versions = within(toggle.parentElement!).getAllByRole("listitem");
    expect(versions.map((li) => li.textContent)).toEqual(["survey", "data collection"]);
  });

  it("collects a retired row with no live successor under its phase, not as a choice", () => {
    render(<DecisionsPanel phase="design" decisions={ROWS} />);
    openPanel();
    const retired = screen.getByRole("button", { name: "1 retired decision (no longer in force)" });
    fireEvent.click(retired);
    expect(screen.getByText("Capture GPS?")).toBeInTheDocument();
  });

  it("renders nothing for a phase whose only rows are someone else's", () => {
    const { container } = render(<DecisionsPanel phase="commcare" decisions={ROWS} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("splitSuperseded", () => {
  it("treats a cycle or a dangling id as retired, never as live", () => {
    const { live, retired, earlierBy } = splitSuperseded([
      dec({ id: "a", superseded_by: "b" }),
      dec({ id: "b", superseded_by: "a" }),
      dec({ id: "c", superseded_by: "nowhere" }),
      dec({ id: "d" }),
    ]);
    expect(live.map((d) => d.id)).toEqual(["d"]);
    expect(retired.map((d) => d.id)).toEqual(["a", "b", "c"]);
    expect(earlierBy.size).toBe(0);
  });

  it("reads a snapshot cached before the field existed as all-live", () => {
    const rows = [dec({ id: "x" }), dec({ id: "y" })];
    expect(splitSuperseded(rows).live).toHaveLength(2);
  });
});
