import { describe, expect, it } from "vitest";

import { parseLedger } from "../ledgerParse";

/** Taken verbatim from the real export of
 *  ACE/hh-poverty-targeting/feedback/20260727-sophie-feintuch-ledger, so a
 *  change to the plugin's output shape fails here rather than on screen. */
const REAL = String.raw`## \[a\] §3 Instrument — implement Annex A verbatim

> Fields for the survey questions, in addition to the photo, GPS, consent, and both name fields must be required rather than optional  
> 

- **SHIPPED** · decision — decisions.yaml § required-vs-optional-fields — every survey field is REQUIRED. — decisions.yaml\#required-vs-optional-fields *(run 20260728-0705)*

## \[b\] §5 Visit definition — FLW physically at the household (GPS)

> A constraint's message has to be actionable on the screen where it appears.  
> 

- **SHIPPED** · skill fix — ace\#980 — a mechanical constraint-locality parser now rejects a constraint whose message cannot be satisfied on the screen it appears on. — [https://github.com/dimagi-internal/ace/issues/980](https://github.com/dimagi-internal/ace/issues/980) *(run 20260728-0705)*
- **SHIPPED** · skill fix — ace\#996 — a relevance-reachability check now catches conditions referencing LATER answers, which had made outcome\_note unreachable. — [https://github.com/dimagi-internal/ace/issues/996](https://github.com/dimagi-internal/ace/issues/996) *(run 20260728-0705)*

## \[d\] §5 \[ACE\] Visit flow

> visit\_outcome is the first question in the form, which is impossible for an FLW to answer at that point:  
> 1\. Is the dwelling occupied? (observation)  
> 2\. If occupied: is an eligible adult respondent available?  
> Then: visit\_outcome \= if(occupied \= 'no', 'vacant', 'completed')

- **SHIPPED** · skill fix — ace\#979 — visit\_outcome is now computed. — [https://github.com/dimagi-internal/ace/issues/979](https://github.com/dimagi-internal/ace/issues/979) *(run 20260728-0705)*
`;

describe("parseLedger", () => {
  it("finds every item with its anchor", () => {
    const items = parseLedger(REAL)!;
    expect(items).toHaveLength(3);
    expect(items.map((i) => i.id)).toEqual(["a", "b", "d"]);
    expect(items[0].anchor).toBe("§3 Instrument — implement Annex A verbatim");
    // The anchor's own brackets survive; only the leading [id] is taken off.
    expect(items[2].anchor).toBe("§5 [ACE] Visit flow");
  });

  it("shortens a GitHub URL to something readable", () => {
    const [, b] = parseLedger(REAL)!;
    expect(b.dispositions[0].ref).toBe("ace#980");
    expect(b.dispositions[0].href).toBe("https://github.com/dimagi-internal/ace/issues/980");
  });

  it("does not say the reference twice", () => {
    // The ledger's prose opens with "ace#980 — …"; with the ref shown as its
    // own link that is a stutter.
    const [, b] = parseLedger(REAL)!;
    expect(b.dispositions[0].text.startsWith("ace#980")).toBe(false);
    expect(b.dispositions[0].text).toMatch(/^a mechanical constraint-locality parser/);
  });

  it("promotes a trailing reference that has no URL", () => {
    const [a] = parseLedger(REAL)!;
    expect(a.dispositions[0].ref).toBe("decisions.yaml#required-vs-optional-fields");
    expect(a.dispositions[0].href).toBeNull();
    expect(a.dispositions[0].text.endsWith("REQUIRED.")).toBe(true);
  });

  it("drops the run suffix that repeats on every line", () => {
    for (const item of parseLedger(REAL)!) {
      for (const d of item.dispositions) {
        expect(d.text).not.toContain("20260728-0705");
      }
    }
  });

  it("resolves every escape, including the underscores", () => {
    const joined = JSON.stringify(parseLedger(REAL)!);
    expect(joined).not.toContain("\\\\_");
    expect(joined).not.toContain("\\\\#");
    expect(joined).not.toContain("\\\\=");
    const [, , d] = parseLedger(REAL)!;
    expect(d.quote).toContain("visit_outcome");
    expect(d.quote).toContain("= if(occupied = 'no'");
  });

  it("keeps the reviewer's line structure instead of flattening it", () => {
    const [, , d] = parseLedger(REAL)!;
    expect(d.quote.split("\n").length).toBeGreaterThan(2);
    expect(d.quote).toContain("1. Is the dwelling occupied?");
  });

  it("captures status and kind separately", () => {
    const [a] = parseLedger(REAL)!;
    expect(a.dispositions[0].status).toBe("SHIPPED");
    expect(a.dispositions[0].kind).toBe("decision");
  });

  // ---- the fallback, which is what makes parsing a generated format safe --
  it("returns null for a body that isn't this shape", () => {
    expect(parseLedger("Just some prose with no headings at all.")).toBeNull();
    expect(parseLedger("")).toBeNull();
    expect(parseLedger("   ")).toBeNull();
  });

  it("returns null when headings parse but nothing under them does", () => {
    // Half a parse is worse than none — the caller renders the markdown.
    expect(parseLedger("## \\[a\\] An anchor\n\nsome prose, no bullets\n")).toBeNull();
  });

  it("keeps an item whose disposition has no reference at all", () => {
    const items = parseLedger(
      "## \\[z\\] Something\n\n> a comment\n\n- **UNROUTED** · — nobody picked this up\n",
    )!;
    expect(items).toHaveLength(1);
    expect(items[0].dispositions[0].status).toBe("UNROUTED");
    expect(items[0].dispositions[0].text).toContain("nobody picked this up");
  });
});
