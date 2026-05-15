import { useState } from "react";
import { useBeatEditor } from "./BeatEditorContext";
import { submitEditBatch, getVideoRun } from "@/api/videos";
import type { ProgramSpec } from "./types";

interface Props {
  onSpecRefetched?: (s: ProgramSpec) => void;
}

export function BeatEditorTopBar({ onSpecRefetched }: Props) {
  const { state, dispatch, workspaceSlug, programSlug, runId } = useBeatEditor();
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const dirty = state.buffer.length > 0;
  const saveState = state.saveState;
  const status = saveState.status;

  const onSave = async () => {
    if (!dirty || status === "saving") return;
    dispatch({ type: "SAVE_START" });
    try {
      await submitEditBatch(workspaceSlug, programSlug, runId, state.buffer);
      // Refetch the canonical spec so effectiveSpec re-derives from server truth.
      const fresh = await getVideoRun(workspaceSlug, programSlug, runId);
      if (fresh.spec) {
        dispatch({ type: "REPLACE_SPEC", spec: fresh.spec });
        onSpecRefetched?.(fresh.spec);
      } else {
        dispatch({ type: "CLEAR_BUFFER" });
      }
      dispatch({ type: "SAVE_OK", at: Date.now() });
    } catch (e: unknown) {
      dispatch({ type: "SAVE_ERROR", message: e instanceof Error ? e.message : String(e) });
    }
  };

  const onDiscard = () => {
    if (!confirmDiscard) {
      setConfirmDiscard(true);
      setTimeout(() => setConfirmDiscard(false), 3000);
      return;
    }
    dispatch({ type: "CLEAR_BUFFER" });
    setConfirmDiscard(false);
  };

  let label: string;
  if (saveState.status === "saving") {
    label = "Saving…";
  } else if (saveState.status === "error") {
    label = `⚠ Save failed: ${saveState.message}`;
  } else if (saveState.status === "saved" && !dirty) {
    label = `✓ Saved at ${new Date(saveState.at).toLocaleTimeString()}`;
  } else if (dirty) {
    label = `${state.buffer.length} edit${state.buffer.length === 1 ? "" : "s"} pending`;
  } else {
    label = "No unsaved changes";
  }

  return (
    <div className="sticky top-0 z-30 flex items-center gap-3 rounded-md border bg-background p-3 shadow-sm">
      <div className={dirty ? "text-sm font-medium text-amber-700" : "text-sm text-muted-foreground"}>
        {label}
      </div>
      {dirty && (
        <>
          <button
            type="button"
            onClick={onSave}
            disabled={status === "saving"}
            className="ml-auto rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            Save changes
          </button>
          <button
            type="button"
            onClick={onDiscard}
            className="rounded border px-3 py-1.5 text-sm"
          >
            {confirmDiscard ? "Click again to confirm" : "Discard all"}
          </button>
        </>
      )}
    </div>
  );
}
