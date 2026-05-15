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
}

const Ctx = createContext<ContextValue | null>(null);

interface Props {
  workspaceSlug: string;
  programSlug: string;
  runId: string;
  spec: ProgramSpec;
  children: ReactNode;
}

export function BeatEditorProvider({ workspaceSlug, programSlug, runId, spec, children }: Props) {
  const [state, dispatch] = useReducer(editorReducer, spec, initialEditorState);
  const effectiveSpec = useMemo(
    () => applyOps(state.spec, state.buffer),
    [state.spec, state.buffer],
  );
  const value: ContextValue = { state, effectiveSpec, dispatch, programSlug, runId, workspaceSlug };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBeatEditor(): ContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useBeatEditor must be used inside <BeatEditorProvider>");
  return v;
}
