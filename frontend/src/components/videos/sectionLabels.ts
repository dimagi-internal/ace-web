// Plain-language labels keyed by beat id. The schema-level term is "beat"
// (screenwriting jargon); the UI calls them "sections". Mirrors the
// SECTION_LABELS in build-clip-explorer.ts:113 — keep in sync.

export interface SectionLabel {
  name: string;
  subtitle: string;
}

export const SECTION_LABELS: Record<string, SectionLabel> = {
  hook:    { name: "Opening tagline",       subtitle: "Headline that frames the video." },
  cycle:   { name: "How Connect works",     subtitle: "Learn → Deliver → Verify → Pay cycle." },
  handoff: { name: "Program handoff",       subtitle: "Names this specific program." },
  scene:   { name: "Field footage",         subtitle: "Real footage from the program location." },
  problem: { name: "Headline stat",         subtitle: "One big number that frames the problem." },
  product: { name: "Connect app walkthrough", subtitle: "Short phone-frame clips." },
  impact:  { name: "Results numbers",       subtitle: "Two big numbers — what the program delivered." },
  cta:     { name: "End card",              subtitle: "Logo + tagline + 'become a partner'." },
};

export function sectionLabel(beatId: string): SectionLabel {
  return SECTION_LABELS[beatId] ?? { name: beatId, subtitle: "" };
}
