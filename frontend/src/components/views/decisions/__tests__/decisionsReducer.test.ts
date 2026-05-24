import { describe, expect, it } from "vitest";

import {
  decisionsReducer,
  initialDecisionsEditState,
  type DecisionsEditState,
} from "../decisionsReducer";

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

describe("MERGE_REMOTE", () => {
  it("seeds buffer from empty", () => {
    const state = initialDecisionsEditState();
    const next = decisionsReducer(state, {
      type: "MERGE_REMOTE",
      edits: {
        "d-001": { new_answer: "No", editor_email: "alice@d.com", editor_name: "Alice" },
      },
    });
    expect(next.buffer).toHaveLength(1);
    expect(next.buffer[0].row_id).toBe("d-001");
    expect(next.buffer[0].new_answer).toBe("No");
    expect(next.buffer[0].editor_email).toBe("alice@d.com");
  });

  it("updates existing row", () => {
    const state: DecisionsEditState = {
      buffer: [{ row_id: "d-001", new_answer: "Yes", editor_email: "a@b.com", editor_name: "A" }],
    };
    const next = decisionsReducer(state, {
      type: "MERGE_REMOTE",
      edits: {
        "d-001": { new_answer: "No", editor_email: "bob@d.com", editor_name: "Bob" },
      },
    });
    expect(next.buffer).toHaveLength(1);
    expect(next.buffer[0].new_answer).toBe("No");
    expect(next.buffer[0].editor_email).toBe("bob@d.com");
  });

  it("preserves rows not in the remote payload", () => {
    const state: DecisionsEditState = {
      buffer: [{ row_id: "d-001", new_answer: "A", editor_email: "a@b.com", editor_name: "A" }],
    };
    const next = decisionsReducer(state, {
      type: "MERGE_REMOTE",
      edits: {
        "d-002": { new_answer: "B", editor_email: "b@b.com", editor_name: "B" },
      },
    });
    expect(next.buffer).toHaveLength(2);
  });
});
