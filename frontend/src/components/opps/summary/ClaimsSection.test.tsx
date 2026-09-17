import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { OppSummaryPayload } from "@/api/oppSummary";
import { ClaimsSection } from "@/components/opps/summary/ClaimsSection";

type Claims = NonNullable<OppSummaryPayload["claims"]>;
type Claim = Claims["people"][number]["claims"][number];

/**
 * "What changed because you asked."
 *
 * These are not "does it render" tests. Each one guards a property the
 * design leans on, and a page that lost any of them would look finished
 * and be useless:
 *
 * - every claim renders WHICHEVER WAY IT WENT (the denominator property)
 * - a claim the counterpart authored is marked as hers
 * - a `judged` verdict is qualified
 * - the audit `evidence` is not what a counterpart reads
 */

const claim = (over: Partial<Claim>): Claim => ({
  id: "c1",
  claim: "The Deliver app carries no payment marker on consumption support.",
  verdict: "MET",
  evidence_kind: "probed",
  authored_by: "ace",
  person: "Sophie Feintuch",
  quote: null,
  artifact: "deliver-app",
  checkable_at: "commcare-setup",
  says: null,
  evidence: null,
  would_settle_it: null,
  ...over,
});

const set = (claims: Claim[], over: Partial<Claims> = {}): Claims => ({
  summary: "1/1 met",
  total: claims.length,
  all_met: true,
  counts: { met: 1, unmet: 0, not_reached: 0, indeterminate: 0, unanswered: 0 },
  error: null,
  people: [{ person: "Sophie Feintuch", claims }],
  ...over,
});

describe("ClaimsSection", () => {
  it("renders every claim whichever way it went — an unmet one accuses", () => {
    render(
      <ClaimsSection
        claims={set(
          [
            claim({ id: "a", claim: "Claim A.", verdict: "MET" }),
            claim({ id: "b", claim: "Claim B.", verdict: "UNMET" }),
            claim({ id: "c", claim: "Claim C.", verdict: "NOT REACHED" }),
            claim({ id: "d", claim: "Claim D.", verdict: "INDETERMINATE" }),
          ],
          { summary: "1/4 met, 1 not met, 1 never reached, 1 indeterminate" },
        )}
      />,
    );
    for (const text of ["Claim A.", "Claim B.", "Claim C.", "Claim D."]) {
      expect(screen.getByText(new RegExp(text))).toBeInTheDocument();
    }
    expect(screen.getByText("Not met")).toBeInTheDocument();
    expect(screen.getByText("Never reached")).toBeInTheDocument();
    expect(screen.getByText("Indeterminate")).toBeInTheDocument();
  });

  it("leads with the tally, so a reader knows the shape before the detail", () => {
    render(<ClaimsSection claims={set([claim({})], { summary: "6/8 met, 2 not met" })} />);
    expect(screen.getByText("6/8 met, 2 not met")).toBeInTheDocument();
  });

  it("marks a claim the counterpart authored as theirs", () => {
    // The design's ONLY mitigation for ACE writing its own exam.
    render(<ClaimsSection claims={set([claim({ authored_by: "counterpart" })])} />);
    expect(screen.getByText(/you asked for this one/i)).toBeInTheDocument();
  });

  it("does not mark an ACE-authored claim as the counterpart's", () => {
    render(<ClaimsSection claims={set([claim({ authored_by: "ace" })])} />);
    expect(screen.queryByText(/you asked for this one/i)).not.toBeInTheDocument();
  });

  it("qualifies a judged verdict so it reads weaker than a probed one", () => {
    render(<ClaimsSection claims={set([claim({ evidence_kind: "judged" })])} />);
    expect(screen.getByText(/judged, not probed/i)).toBeInTheDocument();
  });

  it("does not qualify a probed verdict", () => {
    render(<ClaimsSection claims={set([claim({ evidence_kind: "probed" })])} />);
    expect(screen.queryByText(/judged, not probed/i)).not.toBeInTheDocument();
  });

  it("REGRESSION CONTROL: a claim with no verdict renders as still open, never as met", () => {
    render(<ClaimsSection claims={set([claim({ verdict: null })])} />);
    expect(screen.getByText("Still open")).toBeInTheDocument();
    expect(screen.queryByText("Met")).not.toBeInTheDocument();
  });

  it("renders the counterpart-facing sentence", () => {
    render(
      <ClaimsSection
        claims={set([claim({ says: "Nobody is paid for consumption support." })])}
      />,
    );
    expect(
      screen.getByText("Nobody is paid for consumption support."),
    ).toBeInTheDocument();
  });

  it("renders nothing in its place when a claim has no `says`", () => {
    // The fallback is silence about the detail, never the audit record —
    // the payload serves `evidence: null` to a non-member, and the page
    // must not invent a substitute.
    const { container } = render(<ClaimsSection claims={set([claim({ says: null })])} />);
    expect(screen.getByText(/carries no payment marker/)).toBeInTheDocument();
    expect(container.querySelector("details")).toBeNull();
  });

  it("puts the audit record behind a disclosure when a member is served one", () => {
    render(
      <ClaimsSection
        claims={set([
          claim({ evidence: "commcare_download_ccz(domain=connect-ace-prod, …)" }),
        ])}
      />,
    );
    expect(screen.getByText(/How we checked/)).toBeInTheDocument();
    expect(screen.getByText(/commcare_download_ccz/)).toBeInTheDocument();
  });

  it("names what would settle an indeterminate claim", () => {
    render(
      <ClaimsSection
        claims={set([
          claim({ verdict: "INDETERMINATE", would_settle_it: "the published listing" }),
        ])}
      />,
    );
    expect(screen.getByText(/What would settle it: the published listing/)).toBeInTheDocument();
  });

  it("surfaces an unreadable claims file rather than rendering silence", () => {
    render(
      <ClaimsSection
        claims={set([], {
          summary: "the claims recorded for this run could not be read",
          total: 0,
          all_met: false,
          error: "The claims file for this run is not valid YAML.",
          people: [],
        })}
      />,
    );
    expect(
      screen.getByText("The claims file for this run is not valid YAML."),
    ).toBeInTheDocument();
  });

  it("names each person when more than one asked, and nobody when only one did", () => {
    const one = render(<ClaimsSection claims={set([claim({})])} />);
    expect(one.queryByText("Sophie Feintuch")).toBeNull();
    one.unmount();

    render(
      <ClaimsSection
        claims={set([claim({})], {
          people: [
            { person: "Sophie Feintuch", claims: [claim({ id: "a" })] },
            { person: "Anne Kuhlmann", claims: [claim({ id: "b" })] },
          ],
        })}
      />,
    );
    expect(screen.getByText("Sophie Feintuch")).toBeInTheDocument();
    expect(screen.getByText("Anne Kuhlmann")).toBeInTheDocument();
  });
});
