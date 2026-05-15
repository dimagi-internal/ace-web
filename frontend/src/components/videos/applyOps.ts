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
      const newRef = `@${op.alias}`;
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
