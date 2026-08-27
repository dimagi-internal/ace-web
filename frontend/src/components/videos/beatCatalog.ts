// Catalog of the OPTIONAL beats the template editor can add/remove, mirroring
// programs/global_style.yaml (the global timeline) + beats.ts::filterDefaultsForSpec.
//
// The full timeline is fixed and global:
//   hook · cycle · handoff · ai_build · scene · problem · product · impact · cta
// Six of those are CORE (always present); three are OPTIONAL and render only
// when the spec carries the matching content block. Adding/removing a beat in
// the editor adds/removes that block (+ the beat in spec.beats) — it never
// touches global_style.yaml, so it only affects this template's spec.
import type { ProgramSpec, Stat, AiBuild } from "./types";

// Canonical position of every beat in the global timeline (by id). Used to
// insert an added beat back into spec.beats in the right place.
export const BEAT_ORDER: Record<string, number> = {
  hook: 0,
  cycle: 1,
  handoff: 2,
  ai_build: 3,
  scene: 4,
  problem: 5,
  product: 6,
  impact: 7,
  cta: 8,
};

export interface OptionalBeatDef {
  id: string;
  kind: string;
  seconds: number;
  label: string;
  /** Is this optional beat currently present in the spec? */
  isPresent: (spec: ProgramSpec) => boolean;
  /** Mutate the spec to ADD the beat's content block (with sensible defaults). */
  addBlock: (spec: ProgramSpec) => void;
  /** Mutate the spec to REMOVE the beat's content block. */
  removeBlock: (spec: ProgramSpec) => void;
}

// The three optional beats. Seconds match global_style.yaml.
export const OPTIONAL_BEATS: OptionalBeatDef[] = [
  {
    id: "ai_build",
    kind: "body_ai_build",
    seconds: 7,
    label: "Card",
    isPresent: (s) => s.ai_build != null && s.active_cut === "ai",
    addBlock: (s) => {
      const card: AiBuild = {
        headline: "Card headline",
        components: ["Point one", "Point two", "Point three"],
        subhead: "",
      };
      s.ai_build = card;
      s.active_cut = "ai";
    },
    removeBlock: (s) => {
      delete s.ai_build;
    },
  },
  {
    id: "problem",
    kind: "body_problem_stat",
    seconds: 10,
    label: "Stat",
    isPresent: (s) => s.problem != null,
    addBlock: (s) => {
      const stat: Stat = { big: "Stat", caption: "What it shows" };
      s.problem = stat;
    },
    removeBlock: (s) => {
      delete s.problem;
    },
  },
  {
    id: "impact",
    kind: "body_impact_stats",
    seconds: 8,
    label: "Cards",
    isPresent: (s) => s.impact != null,
    addBlock: (s) => {
      const cards: Stat[] = [
        { big: "Stat one", caption: "What it shows" },
        { big: "Stat two", caption: "What it shows" },
      ];
      s.impact = cards;
    },
    removeBlock: (s) => {
      delete s.impact;
    },
  },
];

export function optionalBeatById(id: string): OptionalBeatDef | undefined {
  return OPTIONAL_BEATS.find((b) => b.id === id);
}

export function isOptionalBeat(id: string): boolean {
  return OPTIONAL_BEATS.some((b) => b.id === id);
}
