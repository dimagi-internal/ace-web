import { describe, expect, it } from "vitest";

import { parseFrontmatter } from "../frontmatter";

describe("parseFrontmatter", () => {
  it("parses a plain fence", () => {
    const r = parseFrontmatter("---\ntitle: PDD\n---\n# Body");
    expect(r.metadata).toEqual([["title", "PDD"]]);
    expect(r.body).toBe("# Body");
  });

  it("tolerates Drive's two-space hard-break markers on the fences", () => {
    const r = parseFrontmatter("---  \ntitle: Household Poverty Targeting Survey  \nstatus: draft  \n---  \n# Body");
    expect(r.metadata).toEqual([
      ["title", "Household Poverty Targeting Survey"],
      ["status", "draft"],
    ]);
    expect(r.body).toBe("# Body");
  });

  it("leaves a document without front matter alone", () => {
    expect(parseFrontmatter("# Just a doc").metadata).toBeNull();
  });
});
