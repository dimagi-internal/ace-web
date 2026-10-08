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
  shortDay,
} from "@/components/opps/decisions/lineage/lineageDisplay";

import { FRESH_CLONE_MEMBER, FRESH_CLONE_OUTSIDER } from "./freshCloneLineage.fixture";
import { MEMBER_LINEAGE, OUTSIDER_LINEAGE } from "./sparkLineage.fixture";

const IDS = Object.keys(MEMBER_LINEAGE.origins);

describe("lineage words", () => {
  it("formats days without shifting time zones", () => {
    expect(formatDay("2026-09-25")).toBe("25 Sep 2026");
    expect(formatDay("2026-10-04T23:30:00+00:00")).toBe("4 Oct 2026");
    expect(formatDay("")).toBe("");
    expect(shortDay("2026-10-04")).toBe("4 Oct");
  });

  it("names runs for a member and versions for an outsider", () => {
    const m = (id: string) => originBadge(MEMBER_LINEAGE.origins[id], MEMBER_LINEAGE, false)?.label;
    const o = (id: string) =>
      originBadge(OUTSIDER_LINEAGE.origins[id], OUTSIDER_LINEAGE, true)?.label;
    // Every label says WHO decided and WHERE (run + date).
    expect(m("working-language")).toBe(
      "decided by ACE in run 20260925-1536 (25 Sep), carried unchanged",
    );
    expect(o("working-language")).toBe(
      "decided by ACE in the 25 Sep 2026 version, carried over unchanged",
    );
    // The copy into spark changed it (the partner's own program): said as a copy.
    expect(m("program-reuse-vs-create-spark")).toBe(
      "changed by ACE when copied into this workspace",
    );
    expect(o("program-reuse-vs-create-spark")).toBe("changed by ACE when this copy was made");
    // The seeded fork changed it; the clone only copied that.
    expect(m("learn-latitude-starting-quiz")).toBe(
      "changed by ACE in run 20261001-2208 (1 Oct), was different in run 20260926-1800 (26 Sep)",
    );
    // A same-workspace re-run that reached the same answer — never "re-affirmed".
    expect(m("connect-latitude-payment-amount-spark")).toBe(
      "re-decided in run 20261001-2208 (1 Oct), same answer as run 20260925-1536 (25 Sep)",
    );
    expect(o("connect-latitude-payment-amount-spark")).toBe(
      "re-checked in the 1 Oct 2026 version, unchanged",
    );
    expect(m("open-question-recording-path-whole-community-group-declines")).toBe(
      "decided by ACE in this run (1 Oct)",
    );
    expect(o("open-question-recording-path-whole-community-group-declines")).toBe(
      "decided by ACE in this version",
    );
    expect(m("sol-devices-and-system-of-record-2208")).toBe("set by a person");
  });

  it("traces a clone of a fresh run to the run that decided it — never 'carried'", () => {
    const m = (id: string) =>
      originBadge(FRESH_CLONE_MEMBER.origins[id], FRESH_CLONE_MEMBER, false);
    const o = (id: string) =>
      originBadge(FRESH_CLONE_OUTSIDER.origins[id], FRESH_CLONE_OUTSIDER, true)?.label;
    expect(m("gps-per-meeting-capture")?.label).toBe(
      "decided by ACE in run 20261004-1706 (4 Oct)",
    );
    expect(m("gps-per-meeting-capture")?.title).toBe(
      "ACE decided this in dimagi-team / 20261004-1706 (4 Oct 2026). This run is a copy " +
        "of it, made on 6 Oct 2026 — copying is not a decision.",
    );
    expect(o("gps-per-meeting-capture")).toBe("decided by ACE in the 4 Oct 2026 version");
    // The Connect re-mint (`<id>-dimagi-team` → `<id>`, same value) is not an event.
    expect(m("connect-rule-one-paid-per-worker-per-day")?.label).toBe(
      "decided by ACE in run 20261004-1706 (4 Oct)",
    );
    // A re-mint that changed the value is the copy changing it.
    expect(m("connect-opportunity")?.label).toBe(
      "changed by ACE when copied into this workspace (6 Oct)",
    );
    expect(m("connect-opportunity")?.title).toMatch(/Was: dimagi-ace-pm opportunity 812$/);
    expect(m("wo-fixed-costs-fee-structure")?.label).toBe("decided by ACE in this run (4 Oct)");
    for (const id of Object.keys(FRESH_CLONE_MEMBER.origins)) {
      expect(m(id)?.label ?? "").not.toMatch(/carried|re-affirmed|re-decided/);
    }
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
    ).toBe("decided by ACE in run 20260925-1536 (25 Sep), carried unchanged");
  });

  it("buckets reaffirmed as carried and decided as new, and the counts add up", () => {
    expect(filterCounts(IDS, MEMBER_LINEAGE)).toEqual({
      carried: 2, new: 1, changed: 2, human: 1,
    });
    const freshIds = Object.keys(FRESH_CLONE_MEMBER.origins);
    const fresh = filterCounts(freshIds, FRESH_CLONE_MEMBER);
    expect(fresh).toEqual({ carried: 0, new: 4, changed: 1, human: 0 });
    expect(Object.values(fresh).reduce((a, b) => a + b, 0)).toBe(freshIds.length);
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
    expect(screen.getByText("copied into this workspace from")).toBeTruthy();
    expect(screen.getByText("seeded at app build from")).toBeTruthy();
    expect(screen.getByText("forked at demo from")).toBeTruthy();
    expect(screen.getByText("· 26 Sep 2026")).toBeTruthy();
  });

  it("tells an outsider the story in plain words, with no run ids", () => {
    const { container } = render(<LineageStrip lineage={OUTSIDER_LINEAGE} plain />);
    expect(screen.getByText("This version")).toBeTruthy();
    expect(screen.getByText("copied from")).toBeTruthy();
    expect(screen.getByText("redone from the app build stage, building on")).toBeTruthy();
    expect(screen.getByText("the 25 Sep 2026 version")).toBeTruthy();
    expect(container.textContent).not.toMatch(/2026\d{4}-\d{4}|dimagi-team/);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("describes a clone hop as a copy, dated, never as an earlier run", () => {
    render(<LineageStrip lineage={FRESH_CLONE_MEMBER} plain={false} />);
    expect(screen.getByText("copied into this workspace on 6 Oct 2026 from")).toBeTruthy();
    render(<LineageStrip lineage={FRESH_CLONE_OUTSIDER} plain />);
    expect(screen.getByText("copied on 6 Oct 2026 from")).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: "Changed 2" }));
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
    expect(screen.getByRole("button", { name: "Changed 2" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Changed 2" }));
    expect(current).toBe("all");
  });
});

describe("decision history", () => {
  it("lists the value across the runs, oldest first, following renamed ids", () => {
    // The fixture's payment amount never changed (7500 in every run); move
    // this run's value so there is a history to tell.
    const id = "connect-latitude-payment-amount-spark";
    const entries = MEMBER_LINEAGE.histories[id];
    const lineage = {
      ...MEMBER_LINEAGE,
      histories: {
        ...MEMBER_LINEAGE.histories,
        [id]: [...entries.slice(0, -1), { ...entries[entries.length - 1], value: "8000" }],
      },
    };
    render(<DecisionLineageHistory lineage={lineage} id={id} />);
    fireEvent.click(screen.getByText("How this decision evolved"));
    // Three runs: the clone is folded into the source it copies.
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toMatch(/25 Sep 2026/);
    expect(items[0].textContent).toMatch(/recorded as connect-latitude-payment-amount/);
    expect(items[2].textContent).toMatch(/\(this run\)/);
    expect(items[2].textContent).toMatch(/copied to spark/);
    expect(screen.getAllByText("(unchanged)")).toHaveLength(1);
  });

  it("draws nothing for a decision carried over verbatim — a clone did not evolve it", () => {
    // Every run of the real fixture holds 7500: the history would be three
    // identical entries, two marked "(unchanged)".
    const { container } = render(
      <DecisionLineageHistory lineage={MEMBER_LINEAGE} id="connect-latitude-payment-amount-spark" />,
    );
    expect(container.textContent).toBe("");
  });

  describe("two found entries (the clone shape)", () => {
    const [source] = MEMBER_LINEAGE.histories["working-language"];
    const sourceValue = source.value ?? "";
    const twoEntries = (current: string) => ({
      ...MEMBER_LINEAGE,
      histories: {
        "working-language": [
          source,
          { ...source, workspace: "spark", run_id: "20261004-1706", date: "2026-10-04", value: current },
        ],
      },
    });

    it("same value → nothing rendered", () => {
      const { container } = render(
        <DecisionLineageHistory lineage={twoEntries(sourceValue)} id="working-language" />,
      );
      expect(container.textContent).toBe("");
      expect(screen.queryByText("How this decision evolved")).toBeNull();
    });

    it("same value up to case and spacing → nothing rendered (the '(unchanged)' rule)", () => {
      const { container } = render(
        <DecisionLineageHistory
          lineage={twoEntries(`  ${sourceValue.toUpperCase()} `)}
          id="working-language"
        />,
      );
      expect(container.textContent).toBe("");
    });

    it("different value → the disclosure is rendered", () => {
      render(<DecisionLineageHistory lineage={twoEntries("English only")} id="working-language" />);
      expect(screen.getByText("How this decision evolved")).toBeTruthy();
      expect(screen.getByText("(2 runs)")).toBeTruthy();
      fireEvent.click(screen.getByText("How this decision evolved"));
      expect(screen.getByText("English only")).toBeTruthy();
      expect(screen.queryByText("(unchanged)")).toBeNull();
    });
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

  it("marks this run by its flag, not by position — a newer other run can follow it", () => {
    const id = "gps-per-meeting-capture";
    const [current] = FRESH_CLONE_MEMBER.histories[id];
    const newer = {
      ...current, run_id: "20261006-0900", date: "2026-10-06", current: false,
      in_lineage: false, copied_to: undefined, value: "Not captured",
    };
    render(
      <DecisionLineageHistory
        lineage={{ ...FRESH_CLONE_MEMBER, histories: { [id]: [current, newer] } }}
        id={id}
      />,
    );
    fireEvent.click(screen.getByText("How this decision evolved"));
    const items = screen.getAllByRole("listitem");
    expect(items[0].textContent).toMatch(/\(this run\)/);
    expect(items[1].textContent).not.toMatch(/\(this run\)/);
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
    expect(screen.getByText("changed by ACE in the 1 Oct 2026 version")).toBeTruthy();
  });

  it("hides the everywhere-badge of a copied run on the summary, not the new rows", () => {
    const { container } = render(
      <>
        <OriginBadge lineage={FRESH_CLONE_OUTSIDER} id="gps-per-meeting-capture" plain hideCarried />
        <OriginBadge
          lineage={FRESH_CLONE_OUTSIDER}
          id="wo-fixed-costs-fee-structure"
          plain
          hideCarried
        />
      </>,
    );
    expect(container.textContent).toBe("decided by ACE in this version");
  });
});
