export interface EditOp {
  row_id: string;
  new_answer: string;
}

export interface DecisionsEditState {
  /** Buffered edits, coalesced by row_id, preserving insertion order. */
  buffer: EditOp[];
}

export function initialDecisionsEditState(): DecisionsEditState {
  return { buffer: [] };
}

export type DecisionsEditAction =
  | { type: "APPLY_EDIT"; row_id: string; new_answer: string }
  | { type: "REVERT_EDIT"; row_id: string }
  | { type: "DISCARD_ALL" };

export function decisionsReducer(
  state: DecisionsEditState,
  action: DecisionsEditAction,
): DecisionsEditState {
  switch (action.type) {
    case "APPLY_EDIT": {
      const existing = state.buffer.findIndex((e) => e.row_id === action.row_id);
      if (existing === -1) {
        return {
          buffer: [...state.buffer, { row_id: action.row_id, new_answer: action.new_answer }],
        };
      }
      const next = state.buffer.slice();
      next[existing] = { row_id: action.row_id, new_answer: action.new_answer };
      return { buffer: next };
    }
    case "REVERT_EDIT": {
      const idx = state.buffer.findIndex((e) => e.row_id === action.row_id);
      if (idx === -1) return state; // referential equality preserved
      return { buffer: state.buffer.filter((_, i) => i !== idx) };
    }
    case "DISCARD_ALL": {
      if (state.buffer.length === 0) return state;
      return { buffer: [] };
    }
  }
}
