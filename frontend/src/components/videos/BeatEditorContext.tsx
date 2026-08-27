import { createContext, useContext, useMemo, useReducer, type ReactNode } from "react";
import { applyOps } from "./applyOps";
import { editorReducer, initialEditorState, type EditorAction } from "./editorReducer";
import type { EditorState, ProgramSpec } from "./types";

interface ContextValue {
  state: EditorState;
  effectiveSpec: ProgramSpec;
  dispatch: (a: EditorAction) => void;
  programSlug: string;
  runId: string;
  workspaceSlug: string;
  onSave?: (effectiveSpec: ProgramSpec) => Promise<void>;
  // True in the TEMPLATE editor (where save = whole-spec, client-applied via
  // onSave). Enables structural edits (add/remove beat) + the ai_build-card,
  // caption, and lower-third widgets — whose ops apply client-side only and
  // are NOT understood by the workbench /edit-batch backend. Off in the
  // per-run workbench editor, which keeps its content-only edit set.
  fullEdit: boolean;
}

const Ctx = createContext<ContextValue | null>(null);

interface Props {
  workspaceSlug: string;
  programSlug: string;
  runId: string;
  spec: ProgramSpec;
  children: ReactNode;
  onSave?: (effectiveSpec: ProgramSpec) => Promise<void>;
}

export function BeatEditorProvider({ workspaceSlug, programSlug, runId, spec, children, onSave }: Props) {
  const [state, dispatch] = useReducer(editorReducer, spec, initialEditorState);
  const effectiveSpec = useMemo(
    () => applyOps(state.spec, state.buffer),
    [state.spec, state.buffer],
  );
  const value: ContextValue = {
    state, effectiveSpec, dispatch, programSlug, runId, workspaceSlug, onSave,
    fullEdit: onSave != null,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBeatEditor(): ContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useBeatEditor must be used inside <BeatEditorProvider>");
  return v;
}
