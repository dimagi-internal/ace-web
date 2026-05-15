import { describe, expect, it } from "vitest";
import type { EditorState, PendingChange, ProgramSpec, WidgetRef } from "../types";
import { editorReducer, initialEditorState } from "../editorReducer";

const spec: ProgramSpec = {
  slug: "demo", name: "Demo",
  narration: { by_beat: {} },
};

function fresh(): EditorState {
  return initialEditorState(spec);
}

describe("editorReducer", () => {
  it("initial state has empty buffer + idle save", () => {
    const s = fresh();
    expect(s.buffer).toEqual([]);
    expect(s.saveState.status).toBe("idle");
    expect(s.drawerTarget).toBeNull();
  });

  it("OPEN_DRAWER sets target", () => {
    const target: WidgetRef = { kind: "narration", beatId: "hook" };
    const s = editorReducer(fresh(), { type: "OPEN_DRAWER", target });
    expect(s.drawerTarget).toEqual(target);
  });

  it("CLOSE_DRAWER clears target", () => {
    const target: WidgetRef = { kind: "narration", beatId: "hook" };
    let s = editorReducer(fresh(), { type: "OPEN_DRAWER", target });
    s = editorReducer(s, { type: "CLOSE_DRAWER" });
    expect(s.drawerTarget).toBeNull();
  });

  it("APPEND_OP appends a new op", () => {
    const op: PendingChange = { op: "set-narration", beatId: "hook", text: "Hi" };
    const s = editorReducer(fresh(), { type: "APPEND_OP", op });
    expect(s.buffer).toEqual([op]);
  });

  it("APPEND_OP coalesces same-target narration", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "hook", text: "v1" } });
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "hook", text: "v2" } });
    expect(s.buffer).toHaveLength(1);
    expect(s.buffer[0]).toMatchObject({ text: "v2" });
  });

  it("APPEND_OP does NOT coalesce different-beat narration", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "hook", text: "a" } });
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "scene", text: "b" } });
    expect(s.buffer).toHaveLength(2);
  });

  it("APPEND_OP coalesces same-target clip trim", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: {
      op: "set-clip-trim", kind: "product-beat", index: 0,
      start_seconds: 1, duration_seconds: 2,
    }});
    s = editorReducer(s, { type: "APPEND_OP", op: {
      op: "set-clip-trim", kind: "product-beat", index: 0,
      start_seconds: 1.5, duration_seconds: 2.5,
    }});
    expect(s.buffer).toHaveLength(1);
    expect(s.buffer[0]).toMatchObject({ start_seconds: 1.5 });
  });

  it("APPEND_OP coalescing preserves order when replacing", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "a", text: "1" } });
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "b", text: "2" } });
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "a", text: "1b" } });
    expect(s.buffer.map(o => (o as any).beatId)).toEqual(["a", "b"]);
    expect((s.buffer[0] as any).text).toBe("1b");
  });

  it("CLEAR_BUFFER empties the queue", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "h", text: "x" } });
    s = editorReducer(s, { type: "CLEAR_BUFFER" });
    expect(s.buffer).toEqual([]);
  });

  it("REPLACE_SPEC swaps spec and clears buffer", () => {
    let s = fresh();
    s = editorReducer(s, { type: "APPEND_OP", op: { op: "set-narration", beatId: "h", text: "x" } });
    const newSpec: ProgramSpec = { ...spec, name: "Renamed" };
    s = editorReducer(s, { type: "REPLACE_SPEC", spec: newSpec });
    expect(s.spec.name).toBe("Renamed");
    expect(s.buffer).toEqual([]);
  });

  it("SAVE_START / SAVE_OK / SAVE_ERROR transition save state", () => {
    let s = fresh();
    s = editorReducer(s, { type: "SAVE_START" });
    expect(s.saveState.status).toBe("saving");
    s = editorReducer(s, { type: "SAVE_OK", at: 1234 });
    expect(s.saveState).toEqual({ status: "saved", at: 1234 });
    s = editorReducer(s, { type: "SAVE_ERROR", message: "boom" });
    expect(s.saveState).toEqual({ status: "error", message: "boom" });
  });
});
