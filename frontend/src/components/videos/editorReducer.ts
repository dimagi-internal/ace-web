import type { EditorState, PendingChange, ProgramSpec, WidgetRef } from "./types";
import { opCoalesceKey } from "./types";

export type EditorAction =
  | { type: "OPEN_DRAWER"; target: WidgetRef }
  | { type: "CLOSE_DRAWER" }
  | { type: "APPEND_OP"; op: PendingChange }
  | { type: "CLEAR_BUFFER" }
  | { type: "REPLACE_SPEC"; spec: ProgramSpec }
  | { type: "SAVE_START" }
  | { type: "SAVE_OK"; at: number }
  | { type: "SAVE_ERROR"; message: string };

export function initialEditorState(spec: ProgramSpec): EditorState {
  return { spec, buffer: [], drawerTarget: null, saveState: { status: "idle" } };
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "OPEN_DRAWER":
      return { ...state, drawerTarget: action.target };
    case "CLOSE_DRAWER":
      return { ...state, drawerTarget: null };
    case "APPEND_OP": {
      const key = opCoalesceKey(action.op);
      const existingIdx = state.buffer.findIndex((o) => opCoalesceKey(o) === key);
      if (existingIdx >= 0) {
        const next = state.buffer.slice();
        next[existingIdx] = action.op;
        return { ...state, buffer: next };
      }
      return { ...state, buffer: [...state.buffer, action.op] };
    }
    case "CLEAR_BUFFER":
      return { ...state, buffer: [] };
    case "REPLACE_SPEC":
      return { ...state, spec: action.spec, buffer: [], drawerTarget: null };
    case "SAVE_START":
      return { ...state, saveState: { status: "saving" } };
    case "SAVE_OK":
      return { ...state, saveState: { status: "saved", at: action.at } };
    case "SAVE_ERROR":
      return { ...state, saveState: { status: "error", message: action.message } };
  }
}
