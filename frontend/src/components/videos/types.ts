// Shape of the parsed spec.yaml as the editor sees it. Mirrors the
// backend's ruamel doc structure but as TypeScript types. Only fields
// the editor reads are typed here — pass-through for anything else.
export interface ProgramSpec {
  slug: string;
  name: string;
  tagline?: string | null;
  scene?: { clips: (string | ClipObject)[] };
  product?: { beats: (string | ClipObject)[] };
  problem?: Stat;
  impact?: Stat[];
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

export interface Stat {
  big: string;
  caption: string;
  source?: string;
}

// One pending edit. Mirrors backend ops + the coalescing key per op kind.
export type PendingChange =
  | { op: "set-clip-trim"; kind: "scene-clip" | "product-beat"; index: number;
      start_seconds: number; duration_seconds: number }
  | { op: "set-clip-asset"; kind: "scene-clip" | "product-beat"; index: number; alias: string }
  | { op: "set-narration"; beatId: string; text: string }
  | { op: "set-stat"; path: string; big?: string; caption?: string; source?: string };

// What the drawer is currently editing.
export type WidgetRef =
  | { kind: "clip-trim"; clipKind: "scene-clip" | "product-beat"; beatId: string; index: number }
  | { kind: "narration"; beatId: string }
  | { kind: "stat"; beatId: string; path: string };

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
  }
}
