import { useEffect, useRef, useState } from "react";
import { useBeatEditor } from "./BeatEditorContext";
import { sectionLabel } from "./sectionLabels";
import { submitEditBatch, getVideoRun } from "@/api/videos";
import type { PendingChange, ProgramSpec } from "./types";

// Map an op to a human label + the beat-card it lives in (for scroll-to).
function describeOp(op: PendingChange, spec: ProgramSpec): { beatId: string; label: string } {
  if (op.op === "set-narration") {
    return { beatId: op.beatId, label: `Voiceover — ${sectionLabel(op.beatId).name}` };
  }
  if (op.op === "set-stat") {
    if (op.path === "problem") return { beatId: "problem", label: `${sectionLabel("problem").name} — Big number` };
    const m = /^impact\[(\d+)\]$/.exec(op.path);
    if (m) return { beatId: "impact", label: `${sectionLabel("impact").name} — Big number ${parseInt(m[1], 10) + 1}` };
    return { beatId: "impact", label: `Stat (${op.path})` };
  }
  if (op.op === "set-brand") {
    // Brand overrides land on the cycle beat as the "anchor" for the
    // edit-pending row — the tagline + cycle steps both belong to the
    // hook/cycle visual cluster.
    return { beatId: "cycle", label: "Brand template — program override" };
  }
  // set-clip-trim / set-clip-asset
  const beatId = op.kind === "scene-clip" ? "scene" : "product";
  const totalSlots = op.kind === "scene-clip"
    ? (spec.scene?.clips?.length ?? 0)
    : (spec.product?.beats?.length ?? 0);
  const which = totalSlots > 1 ? ` clip ${op.index + 1} of ${totalSlots}` : " clip";
  const action = op.op === "set-clip-asset" ? "Swap" : "Trim";
  return { beatId, label: `${action} ${sectionLabel(beatId).name}${which}` };
}

function scrollToBeat(beatId: string): void {
  document
    .querySelector(`[data-beat-id="${beatId}"]`)
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
}

interface Props {
  onSpecRefetched?: (s: ProgramSpec) => void;
  onRerender?: () => void;
}

export function BeatEditorTopBar({ onSpecRefetched, onRerender }: Props) {
  const { state, effectiveSpec, dispatch, workspaceSlug, programSlug, runId } = useBeatEditor();
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [showPending, setShowPending] = useState(false);

  const dirty = state.buffer.length > 0;
  const saveState = state.saveState;
  const status = saveState.status;

  // Keep the latest onSave callable across renders so the global ⌘+S
  // listener doesn't go stale between buffer changes.
  const onSaveRef = useRef<() => void>(() => {});

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
  onSaveRef.current = onSave;

  // Keyboard shortcuts:
  //   ⌘+S / Ctrl+S         → Save changes (when dirty)
  //   ⌘+Z / Ctrl+Z         → Undo last buffer op
  //   ESC (when saveState=saved) → dismiss the "Saved at" confirmation
  //
  // Skip when an editable element has focus so we don't steal the user's
  // textarea-undo. The drawer's textareas use native browser undo until
  // the user commits Done; only then does the op land in the editor's
  // buffer and become reachable by our ⌘+Z.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const inField = (() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el) return false;
        const tag = el.tagName;
        return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
      })();
      if (e.key === "s" && (e.metaKey || e.ctrlKey) && !e.shiftKey) {
        e.preventDefault();
        onSaveRef.current();
        return;
      }
      if (e.key === "z" && (e.metaKey || e.ctrlKey) && !e.shiftKey && !inField) {
        e.preventDefault();
        dispatch({ type: "UNDO_LAST_OP" });
        return;
      }
      if (e.key === "Escape" && saveState.status === "saved") {
        // Don't preventDefault — ESC also closes drawers etc.
        dispatch({ type: "SAVE_IDLE" });
        return;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [dispatch, saveState.status]);

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

  // Resolve pending ops to {beatId, label} for the hover-list.
  const pendingItems = dirty
    ? state.buffer.map((op) => describeOp(op, effectiveSpec))
    : [];

  // Show the bar when there's something actionable — dirty, mid-save,
  // failed save, or briefly after a successful save (so the user sees
  // confirmation + Re-render CTA before it tucks away). Otherwise hide.
  const showBar =
    dirty ||
    status === "saving" ||
    status === "error" ||
    status === "saved";

  if (!showBar) return null;

  return (
    <div className="sticky top-0 z-30 flex items-center gap-3 rounded-md border bg-background p-3 shadow-sm">
      <div className="relative">
        <button
          type="button"
          onClick={() => dirty && setShowPending((v) => !v)}
          onMouseEnter={() => dirty && setShowPending(true)}
          onMouseLeave={() => setShowPending(false)}
          disabled={!dirty}
          className={
            "rounded px-1 py-0.5 text-sm " +
            (dirty
              ? "cursor-pointer font-medium text-amber-700 hover:bg-amber-100/50"
              : "cursor-default text-muted-foreground")
          }
        >
          {label}
        </button>
        {dirty && showPending && pendingItems.length > 0 && (
          <div
            role="tooltip"
            className="absolute left-0 top-full z-40 mt-1 w-80 rounded-md border bg-background p-2 text-sm shadow-lg"
            onMouseEnter={() => setShowPending(true)}
            onMouseLeave={() => setShowPending(false)}
          >
            <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
              Pending edits — click to jump
            </div>
            <ul className="flex flex-col gap-0.5">
              {pendingItems.map((item, i) => (
                <li key={i}>
                  <button
                    type="button"
                    onClick={() => {
                      scrollToBeat(item.beatId);
                      setShowPending(false);
                    }}
                    className="block w-full truncate rounded px-2 py-1 text-left text-sm hover:bg-accent"
                  >
                    {item.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      {dirty && (
        <>
          <button
            type="button"
            onClick={() => dispatch({ type: "UNDO_LAST_OP" })}
            disabled={status === "saving"}
            title="Undo last edit (⌘+Z)"
            className="ml-auto rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Undo
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={status === "saving"}
            title="Save changes (⌘+S)"
            className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
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
      {!dirty && status === "saved" && onRerender && (
        <button
          type="button"
          onClick={onRerender}
          className="ml-auto rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground"
        >
          Re-render to see changes →
        </button>
      )}
    </div>
  );
}
