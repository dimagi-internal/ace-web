export interface EditOp {
  row_id: string;
  /**
   * The override value. MAY be a string not present in the row's current
   * `options_considered` — in that case the write path (Python
   * `apply_edits_to_decisions_data`) appends it to `options` before
   * setting `override`, keeping the ACE strict-write invariant
   * (`override ∈ options`) intact.
   */
  new_answer: string;
  /** Human's rationale for the override (optional, free text). */
  override_reasoning?: string;
  editor_email?: string;
  editor_name?: string;
}

export interface DecisionsEditState {
  /** Buffered edits, coalesced by row_id, preserving insertion order. */
  buffer: EditOp[];
}

export function initialDecisionsEditState(): DecisionsEditState {
  return { buffer: [] };
}

export type DecisionsEditAction =
  | {
      type: "APPLY_EDIT";
      row_id: string;
      new_answer: string;
      override_reasoning?: string;
      editor_email?: string;
      editor_name?: string;
    }
  | { type: "REVERT_EDIT"; row_id: string }
  | { type: "DISCARD_ALL" }
  | {
      type: "MERGE_REMOTE";
      edits: Record<
        string,
        {
          new_answer: string;
          override_reasoning?: string;
          editor_email: string;
          editor_name: string;
        }
      >;
    };

export function decisionsReducer(
  state: DecisionsEditState,
  action: DecisionsEditAction,
): DecisionsEditState {
  switch (action.type) {
    case "APPLY_EDIT": {
      const existing = state.buffer.findIndex((e) => e.row_id === action.row_id);
      const op: EditOp = {
        row_id: action.row_id,
        new_answer: action.new_answer,
        override_reasoning: action.override_reasoning || undefined,
        editor_email: action.editor_email,
        editor_name: action.editor_name,
      };
      if (existing === -1) {
        return { buffer: [...state.buffer, op] };
      }
      const next = state.buffer.slice();
      next[existing] = op;
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
    case "MERGE_REMOTE": {
      const next = state.buffer.slice();
      for (const [row_id, edit] of Object.entries(action.edits)) {
        const idx = next.findIndex((e) => e.row_id === row_id);
        const op: EditOp = {
          row_id,
          new_answer: edit.new_answer,
          override_reasoning: edit.override_reasoning || undefined,
          editor_email: edit.editor_email,
          editor_name: edit.editor_name,
        };
        if (idx === -1) {
          next.push(op);
        } else {
          next[idx] = op;
        }
      }
      return { buffer: next };
    }
  }
}
