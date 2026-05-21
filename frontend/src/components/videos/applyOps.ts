import type { ProgramSpec, PendingChange, ClipObject } from "./types";

// Pure function: returns a NEW spec with ops applied in order. Does not
// mutate input. Structural sharing where possible; deep-clones only the
// branches that change.
export function applyOps(spec: ProgramSpec, ops: PendingChange[]): ProgramSpec {
  if (ops.length === 0) return spec;
  // Deep clone via JSON to keep this simple — specs are small (~KB).
  // If profiling shows hot path, swap to structuredClone or immer.
  const out: ProgramSpec = JSON.parse(JSON.stringify(spec));
  for (const op of ops) applyOne(out, op);
  return out;
}

function applyOne(spec: ProgramSpec, op: PendingChange): void {
  switch (op.op) {
    case "set-narration": {
      spec.narration ??= { by_beat: {} };
      spec.narration.by_beat ??= {};
      spec.narration.by_beat[op.beatId] = op.text;
      return;
    }
    case "set-clip-trim": {
      const slot = getClipSlot(spec, op.kind, op.index);
      if (!slot) return;
      const obj = ensureClipObject(spec, op.kind, op.index, slot);
      obj.start_seconds = op.start_seconds;
      obj.duration_seconds = op.duration_seconds;
      return;
    }
    case "set-clip-asset": {
      const slot = getClipSlot(spec, op.kind, op.index);
      if (!slot) return;
      // Two op shapes: {alias} or {ref: "library:video/<sub>/<file>"}.
      // For the ref path, derive an alias from the filename stem so
      // the in-memory projection stays consistent until the server
      // round-trip materializes the manifest entry.
      let alias = op.alias;
      if (!alias && op.ref) {
        const m = /^library:video\/[^/]+\/([^/]+?)(\.[^.]+)?$/.exec(op.ref);
        if (m) alias = m[1];
      }
      if (!alias) return;
      const newRef = `@${alias}`;
      if (typeof slot === "string") {
        if (op.kind === "scene-clip") {
          spec.scene!.clips[op.index] = newRef;
        } else {
          spec.product!.beats[op.index] = { asset: newRef };
        }
      } else {
        slot.asset = newRef;
      }
      return;
    }
    case "set-global-template": {
      // Project the override into spec.global_template so widgets
      // keying off effectiveSpec.global_template can flip their
      // "global / program-override" visual without waiting for the
      // save round-trip. Empty values clear the field, matching
      // server semantics. Legacy `spec.brand` from pre-rename writes
      // is also cleared on first edit so we don't leave both keys
      // populated.
      const specWithGlobal = spec as ProgramSpec & {
        global_template?: { tagline?: string; cycle_steps?: string[] };
        brand?: { tagline?: string; cycle_steps?: string[] };
      };
      delete specWithGlobal.brand;
      specWithGlobal.global_template ??= {};
      const gt = specWithGlobal.global_template;
      if (op.tagline !== undefined) {
        if (op.tagline === "") delete gt.tagline;
        else gt.tagline = op.tagline;
      }
      if (op.cycle_steps !== undefined) {
        if (op.cycle_steps.length === 0) delete gt.cycle_steps;
        else gt.cycle_steps = op.cycle_steps;
      }
      if (!gt.tagline && !gt.cycle_steps) {
        delete specWithGlobal.global_template;
      }
      return;
    }
    case "set-stat": {
      const node = resolveStatNode(spec, op.path);
      if (!node) return;
      if (op.big !== undefined) node.big = op.big;
      if (op.caption !== undefined) node.caption = op.caption;
      if (op.source !== undefined) {
        if (op.source === "") delete node.source;
        else node.source = op.source;
      }
      return;
    }
  }
}

function getClipSlot(spec: ProgramSpec, kind: "scene-clip" | "product-beat", index: number):
  string | ClipObject | null
{
  if (kind === "scene-clip") return spec.scene?.clips[index] ?? null;
  return spec.product?.beats[index] ?? null;
}

function ensureClipObject(
  spec: ProgramSpec,
  kind: "scene-clip" | "product-beat",
  index: number,
  current: string | ClipObject,
): ClipObject {
  if (typeof current === "object") return current;
  const obj: ClipObject = { asset: current };
  if (kind === "scene-clip") spec.scene!.clips[index] = obj;
  else spec.product!.beats[index] = obj;
  return obj;
}

function resolveStatNode(spec: ProgramSpec, path: string): { big: string; caption: string; source?: string } | null {
  if (path === "problem") return spec.problem ?? null;
  const m = /^impact\[(\d+)\]$/.exec(path);
  if (!m) return null;
  const i = parseInt(m[1], 10);
  return spec.impact?.[i] ?? null;
}
