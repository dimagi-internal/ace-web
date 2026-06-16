import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";
import type { ClipObject } from "../../types";

interface Props {
  index: number;
  onCommit: () => void;
  onCancel: () => void;
}

// Edits a product beat's caption (the label under each Connect-app clip).
export function CaptionPanel({ index, onCommit, onCancel }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const slot = effectiveSpec.product?.beats[index];
  const initial = (slot && typeof slot === "object" ? (slot as ClipObject).caption : "") ?? "";
  const [text, setText] = useState(initial);
  const dirty = text !== initial;

  const commit = () => {
    if (!dirty) return;
    dispatch({ type: "APPEND_OP", op: { op: "set-caption", index, caption: text } });
    onCommit();
  };

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Caption — the label shown under this clip
        </span>
        <input
          aria-label="caption"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="w-full rounded border bg-background p-2 text-sm"
        />
      </label>
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded border px-3 py-1.5 text-sm">
          Cancel
        </button>
        <button type="button" onClick={commit} disabled={!dirty}
                className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          Done
        </button>
      </div>
    </div>
  );
}
