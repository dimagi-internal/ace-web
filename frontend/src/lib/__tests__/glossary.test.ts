import { describe, expect, it } from "vitest";

import { splitGlossary } from "../glossary";

const terms = (text: string) =>
  splitGlossary(text)
    .filter((s) => s.definition)
    .map((s) => s.text);

describe("splitGlossary", () => {
  it("finds acronyms and keeps the rest as plain text", () => {
    const segs = splitGlossary("Idea → PDD");
    expect(segs.map((s) => s.text).join("")).toBe("Idea → PDD");
    expect(terms("Idea → PDD")).toEqual(["PDD"]);
  });

  it("takes plurals", () => {
    expect(terms("Invite LLOs and FLWs")).toEqual(["LLOs", "FLWs"]);
  });

  it("matches acronyms case-sensitively so slugs don't light up", () => {
    expect(terms("app-release-qa")).toEqual([]);
    expect(terms("App Release QA")).toEqual(["QA"]);
  });

  it("matches phrases in any case, preferring the longest", () => {
    expect(terms("Build the learn App")).toEqual(["learn App"]);
    expect(terms("Deliver app via Nova on HQ")).toEqual(["Deliver app", "Nova", "HQ"]);
  });

  it("doesn't match inside a longer word", () => {
    expect(terms("HQs? no — HQX and PDDs")).toEqual(["HQs", "PDDs"]);
    expect(terms("Connected")).toEqual([]);
  });

  it("returns a single plain segment when nothing matches", () => {
    expect(splitGlossary("Scenarios & acceptance")).toEqual([{ text: "Scenarios & acceptance" }]);
  });
});
