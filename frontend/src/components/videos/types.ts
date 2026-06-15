// Shape of the parsed spec.yaml as the editor sees it. Mirrors the
// backend's ruamel doc structure but as TypeScript types. Only fields
// the editor reads are typed here — pass-through for anything else.
export interface ProgramSpec {
  slug: string;
  name: string;
  tagline?: string | null;
  scene?: { clips: (string | ClipObject)[]; lower_third?: string };
  product?: { beats: (string | ClipObject)[] };
  problem?: Stat;
  impact?: Stat[];
  // The "card" beat (body_ai_build). Present + active_cut === "ai" renders it.
  ai_build?: AiBuild;
  active_cut?: "ai" | "standard";
  narration: { by_beat: Record<string, string>; generator?: string };
  manifest?: Record<string, string>;
  beats?: { id: string; kind: string; seconds: number }[];
  voice?: { provider?: string; voice_id?: string; model?: string };
  music_bed?: Record<string, unknown>;
  // unknown extra fields preserved by ruamel; we don't model them
  [extra: string]: unknown;
}

export interface ClipObject {
  asset: string;
  start_seconds?: number;
  duration_seconds?: number;
  caption?: string;
}

export interface AiBuild {
  headline: string;
  components: string[];
  subhead?: string;
}

export interface Stat {
  big: string;
  caption: string;
  source?: string;
}

// One pending edit. Mirrors backend ops + the coalescing key per op kind.
export type PendingChange =
  | { op: "set-clip-trim"; kind: "scene-clip" | "product-beat"; index: number;
      start_seconds: number; duration_seconds: number }
  | { op: "set-clip-asset"; kind: "scene-clip" | "product-beat"; index: number;
      // Provide one of: `alias` (existing manifest entry) or `ref`
      // ("library:video/<subfolder>/<filename>" — server auto-adds to
      // manifest if not already present).
      alias?: string; ref?: string }
  | { op: "set-narration"; beatId: string; text: string }
  | { op: "set-stat"; path: string; big?: string; caption?: string; source?: string }
  | { op: "set-global-template"; tagline?: string; cycle_steps?: string[] }
  | { op: "set-program-name"; name: string }
  // ── Template-editor-only structural + content ops (client-applied; not
  //    sent to the workbench /edit-batch backend). See applyOps. ──
  | { op: "set-ai-build"; headline?: string; components?: string[]; subhead?: string }
  | { op: "set-caption"; index: number; caption: string }
  | { op: "set-lower-third"; text: string }
  // beatId is one of the optional beats: "ai_build" | "problem" | "impact".
  | { op: "add-beat"; beatId: string }
  | { op: "remove-beat"; beatId: string };

// What the drawer is currently editing.
export type WidgetRef =
  | { kind: "clip-trim"; clipKind: "scene-clip" | "product-beat"; beatId: string; index: number }
  | { kind: "clip-picker"; clipKind: "scene-clip" | "product-beat"; beatId: string; index: number }
  | { kind: "narration"; beatId: string }
  | { kind: "stat"; beatId: string; path: string }
  | { kind: "global-template"; beatId: string }
  | { kind: "program-name"; beatId: string }
  | { kind: "ai-build"; beatId: string }
  | { kind: "caption"; beatId: string; index: number }
  | { kind: "lower-third"; beatId: string };

export interface EditorState {
  spec: ProgramSpec;
  buffer: PendingChange[];
  drawerTarget: WidgetRef | null;
  saveState:
    | { status: "idle" }
    | { status: "saving" }
    | { status: "saved"; at: number }
    | { status: "error"; message: string };
}

// Coalescing key — two ops with the same key collapse to the later one.
export function opCoalesceKey(op: PendingChange): string {
  switch (op.op) {
    case "set-clip-trim":
    case "set-clip-asset":
      return `${op.op}:${op.kind}:${op.index}`;
    case "set-narration":
      return `set-narration:${op.beatId}`;
    case "set-stat":
      return `set-stat:${op.path}`;
    case "set-global-template":
      // Coalesce all brand edits to one slot — last write wins. Both
      // tagline and cycle_steps belong to the same logical "brand
      // override", so a user editing both in one drawer session
      // shouldn't end up with two ops in the buffer.
      return "set-global-template";
    case "set-program-name":
      // Same idea — only one program name; coalesce to a single slot.
      return "set-program-name";
    case "set-ai-build":
      return "set-ai-build";
    case "set-caption":
      return `set-caption:${op.index}`;
    case "set-lower-third":
      return "set-lower-third";
    case "add-beat":
    case "remove-beat":
      // Add/remove of the same optional beat coalesce to one slot — the
      // last toggle wins, so flipping a beat on then off leaves no net op.
      return `beat-presence:${op.beatId}`;
  }
}
