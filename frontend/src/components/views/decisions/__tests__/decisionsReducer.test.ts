import { describe, expect, it } from "vitest";

import { decisionsReducer, initialDecisionsEditState, type DecisionsEditState } from "../decisionsReducer";

const empty: DecisionsEditState = initialDecisionsEditState();

describe("decisionsReducer", () => {
  it("APPLY_EDIT inserts a buffer entry keyed by row_id", () => {
    const state = decisionsReducer(empty, {
      type: "APPLY_EDIT",
      row_id: "a",
      new_answer: "v1",
    });
    expect(state.buffer).toEqual([{ row_id: "a", new_answer: "v1" }]);
  });

  it("APPLY_EDIT coalesces multiple edits to the same row_id", () => {
    let state = decisionsReducer(empty, { type: "APPLY_EDIT", row_id: "a", new_answer: "v1" });
    state = decisionsReducer(state, { type: "APPLY_EDIT", row_id: "a", new_answer: "v2" });
    expect(state.buffer).toEqual([{ row_id: "a", new_answer: "v2" }]);
  });

  it("APPLY_EDIT preserves order across distinct row_ids", () => {
    let state = decisionsReducer(empty, { type: "APPLY_EDIT", row_id: "a", new_answer: "v1" });
    state = decisionsReducer(state, { type: "APPLY_EDIT", row_id: "b", new_answer: "w1" });
    expect(state.buffer.map((e) => e.row_id)).toEqual(["a", "b"]);
  });

  it("REVERT_EDIT removes the row from the buffer", () => {
    let state = decisionsReducer(empty, { type: "APPLY_EDIT", row_id: "a", new_answer: "v1" });
    state = decisionsReducer(state, { type: "REVERT_EDIT", row_id: "a" });
    expect(state.buffer).toEqual([]);
  });

  it("REVERT_EDIT on a row_id not in buffer is a no-op", () => {
    const state = decisionsReducer(empty, { type: "REVERT_EDIT", row_id: "missing" });
    expect(state).toBe(empty);
  });

  it("DISCARD_ALL clears the buffer", () => {
    let state = decisionsReducer(empty, { type: "APPLY_EDIT", row_id: "a", new_answer: "v1" });
    state = decisionsReducer(state, { type: "APPLY_EDIT", row_id: "b", new_answer: "w1" });
    state = decisionsReducer(state, { type: "DISCARD_ALL" });
    expect(state.buffer).toEqual([]);
  });
});
