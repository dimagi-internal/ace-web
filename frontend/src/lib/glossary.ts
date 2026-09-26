/**
 * Plain-English definitions for the acronyms and product names ACE's phase,
 * skill and product names are full of.
 *
 * Someone watching a replay who doesn't know what a PDD or an LLO is stops
 * following at the first one; the presenter explains ACE, not Dimagi's
 * vocabulary. So wherever these names render, a known term gets a dotted
 * underline and its definition on hover.
 *
 * Acronyms match case-sensitively (so "qa" in a slug doesn't light up) and
 * take a plural "s" (LLOs, FLWs). Phrases match case-insensitively.
 */

export interface GlossaryTerm {
  readonly term: string;
  readonly definition: string;
  /** Match regardless of case. Acronyms don't; phrases do. */
  readonly anyCase?: boolean;
}

export const GLOSSARY: readonly GlossaryTerm[] = [
  {
    term: "PDD",
    definition:
      "Program Design Document — the written design of the program. Every later phase builds from it.",
  },
  {
    term: "OCS",
    definition:
      "Open Chat Studio — Dimagi's chatbot platform. ACE builds each program a support chatbot there.",
  },
  {
    term: "LLO",
    definition:
      "Local Leading Organization — the partner organization that runs the program on the ground and manages its frontline workers.",
  },
  {
    term: "FLW",
    definition:
      "Frontline worker — the person in the field who delivers the service and is paid for each verified visit.",
  },
  {
    term: "HQ",
    definition: "CommCare HQ — where CommCare apps are configured, built and released.",
  },
  {
    term: "QA",
    definition: "Quality assurance — automatic structural checks run on a step's output.",
  },
  { term: "UAT", definition: "User acceptance testing — the partner tries it before go-live." },
  {
    term: "RAG",
    definition:
      "Retrieval-augmented generation — the chatbot answers from a collection of the program's own documents.",
  },
  { term: "KPI", definition: "Key performance indicator." },
  {
    term: "Learn app",
    anyCase: true,
    definition: "The CommCare app that trains frontline workers before they start delivering.",
  },
  {
    term: "Deliver app",
    anyCase: true,
    definition: "The CommCare app frontline workers use to record each service visit.",
  },
  {
    term: "Nova",
    definition: "Dimagi's AI app builder — turns a program design into a CommCare app.",
  },
  {
    term: "Connect",
    definition:
      "CommCare Connect — the platform that pays frontline workers for verified service delivery.",
  },
];

export interface GlossarySegment {
  readonly text: string;
  /** Set when this segment is a glossary term. */
  readonly definition?: string;
}

const byLower = new Map(GLOSSARY.map((g) => [g.term.toLowerCase(), g]));

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Longest first so "Learn app" wins over any shorter overlap. Case-insensitive
// at the regex level; case-sensitivity for acronyms is enforced per match.
const PATTERN = new RegExp(
  `\\b(${[...GLOSSARY]
    .sort((a, b) => b.term.length - a.term.length)
    .map((g) => escape(g.term))
    .join("|")})(s?)\\b`,
  "gi",
);

/** Split `text` into plain runs and glossary terms. */
export function splitGlossary(text: string): GlossarySegment[] {
  const out: GlossarySegment[] = [];
  let last = 0;
  for (const m of text.matchAll(PATTERN)) {
    const entry = byLower.get(m[1].toLowerCase());
    if (!entry) continue;
    if (!entry.anyCase && m[1] !== entry.term) continue;
    const start = m.index ?? 0;
    if (start > last) out.push({ text: text.slice(last, start) });
    out.push({ text: m[0], definition: entry.definition });
    last = start + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}
