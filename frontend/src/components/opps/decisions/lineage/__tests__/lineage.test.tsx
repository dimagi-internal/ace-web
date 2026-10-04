import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  DecisionLineageHistory,
  LineageFilterBar,
  LineageStrip,
  OriginBadge,
} from "@/components/opps/decisions/lineage/Lineage";
import {
  filterCounts,
  formatDay,
  originBadge,
} from "@/components/opps/decisions/lineage/lineageDisplay";

import { MEMBER_LINEAGE, OUTSIDER_LINEAGE } from "./sparkLineage.fixture";

const IDS = Object.keys(MEMBER_LINEAGE.origins);

describe("lineage words", () => {
  it("formats days without shifting time zones", () => {
    expect(formatDay("2026-09-25")).toBe("25 Sep 2026");
    expect(formatDay("2026-10-04T23:30:00+00:00")).toBe("4 Oct 2026");
    expect(formatDay("")).toBe("");
  });

  it("names runs for a member and versions for an outsider", () => {
    const m = (id: string) => originBadge(MEMBER_LINEAGE.origins[id], MEMBER_LINEAGE, false)?.label;
    const o = (id: string) =>
      originBadge(OUTSIDER_LINEAGE.origins[id], OUTSIDER_LINEAGE, true)?.label;
    expect(m("working-language")).toBe("carried from dimagi-team / 20260925-1536 unchanged");
    expect(o("working-language")).toBe("carried over unchanged from the 25 Sep 2026 version");
    // The clone's source shares this run's id, so it is named with its workspace.
    expect(m("program-reuse-vs-create-spark")).toBe(
      "carried from dimagi-team / 20261001-2208, changed here",
    );
    expect(o("program-reuse-vs-create-spark")).toBe("changed in this version");
    expect(m("connect-latitude-payment-amount-spark")).toBe(
      "re-affirmed (same as dimagi-team / 20260925-1536)",
    );
    expect(m("open-question-recording-path-whole-community-group-declines")).toBe(
      "new in this run",
    );
    expect(m("sol-devices-and-system-of-record-2208")).toBe("set by a person");
  });

  it("lets a saved human edit win over what the run recorded", () => {
    const badge = originBadge(MEMBER_LINEAGE.origins["working-language"], MEMBER_LINEAGE, false, {
      decided_by_name: "Enock",
      decided_at: "2026-10-03T10:00:00+00:00",
    });
    expect(badge?.label).toBe("set by Enock on 3 Oct 2026");
    // A confirmation is not a change.
    expect(
      originBadge(MEMBER_LINEAGE.origins["working-language"], MEMBER_LINEAGE, false, {
        confirmed: true,
      })?.label,
    ).toBe("carried from dimagi-team / 20260925-1536 unchanged");
  });

  it("buckets reaffirmed as carried for the filter", () => {
    expect(filterCounts(IDS, MEMBER_LINEAGE)).toEqual({
      carried: 3, new: 1, changed: 1, human: 1,
    });
  });
});

describe("lineage strip", () => {
  it("links the runs a member can open and labels the clone source", () => {
    render(<LineageStrip lineage={MEMBER_LINEAGE} plain={false} />);
    const head = screen.getByRole("link", { name: "20261001-2208 (this run)" });
    expect(head.getAttribute("href")).toBe("/ace/w/spark/opps/spark-facilitator/runs/20261001-2208");
    // The source lives in dimagi-team, which this member cannot open: a label.
    expect(screen.getByText("dimagi-team / 20261001-2208")).toBeTruthy();
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByText("cloned from")).toBeTruthy();
    expect(screen.getByText("seeded at app build from")).toBeTruthy();
    expect(screen.getByText("forked at demo from")).toBeTruthy();
    expect(screen.getByText("· 26 Sep 2026")).toBeTruthy();
  });

  it("tells an outsider the story in plain words, with no run ids", () => {
    const { container } = render(<LineageStrip lineage={OUTSIDER_LINEAGE} plain />);
    expect(screen.getByText("This version")).toBeTruthy();
    expect(screen.getByText("a copy of")).toBeTruthy();
    expect(screen.getByText("redone from the app build stage, building on")).toBeTruthy();
    expect(screen.getByText("the 25 Sep 2026 version")).toBeTruthy();
    expect(container.textContent).not.toMatch(/2026\d{4}-\d{4}|dimagi-team/);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("renders nothing for a run with no earlier runs", () => {
    const { container } = render(
      <LineageStrip lineage={{ ...MEMBER_LINEAGE, chain: MEMBER_LINEAGE.chain.slice(0, 1) }} plain={false} />,
    );
    expect(container.textContent).toBe("");
  });
});

describe("lineage filter", () => {
  it("counts each bucket and toggles", () => {
    let current = "all";
    const { rerender } = render(
      <LineageFilterBar
        lineage={MEMBER_LINEAGE}
        ids={IDS}
        filter="all"
        onChange={(f) => {
          current = f;
        }}
      />,
    );
    expect(screen.getByRole("button", { name: "All 6" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Changed 1" }));
    expect(current).toBe("changed");
    rerender(
      <LineageFilterBar
        lineage={MEMBER_LINEAGE}
        ids={IDS}
        filter="changed"
        onChange={(f) => {
          current = f;
        }}
      />,
    );
    expect(screen.getByRole("button", { name: "Changed 1" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Changed 1" }));
    expect(current).toBe("all");
  });
});

describe("decision history", () => {
  it("lists the value across the runs, oldest first, following renamed ids", () => {
    render(
      <DecisionLineageHistory lineage={MEMBER_LINEAGE} id="connect-latitude-payment-amount-spark" />,
    );
    fireEvent.click(screen.getByText("How this decision evolved"));
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[0].textContent).toMatch(/25 Sep 2026/);
    expect(items[0].textContent).toMatch(/recorded as connect-latitude-payment-amount/);
    expect(items[3].textContent).toMatch(/\(this run\)/);
    expect(screen.getAllByText("(unchanged)")).toHaveLength(3);
  });

  it("says who set an overridden value", () => {
    render(
      <DecisionLineageHistory lineage={MEMBER_LINEAGE} id="sol-devices-and-system-of-record-2208" />,
    );
    fireEvent.click(screen.getByText("How this decision evolved"));
    expect(screen.getByText(/^set by a person/)).toBeTruthy();
    expect(screen.getByText("Ask about devices; devices costed separately")).toBeTruthy();
  });

  it("says 'no earlier match' honestly instead of guessing", () => {
    render(
      <DecisionLineageHistory
        lineage={MEMBER_LINEAGE}
        id="open-question-recording-path-whole-community-group-declines"
      />,
    );
    expect(screen.getByText("(no earlier match)")).toBeTruthy();
    fireEvent.click(screen.getByText("How this decision evolved"));
    expect(screen.getAllByText("Not in this run.")).toHaveLength(3);
  });

  it("is members-only: an outsider payload carries no history", () => {
    const { container } = render(
      <DecisionLineageHistory lineage={OUTSIDER_LINEAGE} id="working-language" />,
    );
    expect(container.textContent).toBe("");
  });
});

describe("origin badge", () => {
  it("draws the badge for a row", () => {
    render(<OriginBadge lineage={OUTSIDER_LINEAGE} id="learn-latitude-starting-quiz" plain />);
    expect(screen.getByText("re-affirmed in this version")).toBeTruthy();
  });
});
