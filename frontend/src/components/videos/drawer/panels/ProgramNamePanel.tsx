import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";

interface Props {
  onCommit: () => void;
  onCancel: () => void;
}

/**
 * Rename-program drawer panel.
 *
 * Edits `spec.name` — the display name used by:
 *   - the Remotion handoff card ("Here's how that works for <name>"),
 *   - the editor breadcrumb + run picker,
 *   - the program list at /w/<ws>/videos.
 *
 * Folder slug is NOT touched here (folder renames in Drive are a
 * heavier operation and the slug is the URL stable id). One field,
 * required-non-empty, server trims whitespace and rejects empty.
 */
export function ProgramNamePanel({ onCommit, onCancel }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const initial = (effectiveSpec.name ?? "").trim();
  const [name, setName] = useState(initial);

  const trimmed = name.trim();
  const dirty = trimmed !== initial;
  const valid = trimmed.length > 0;

  const commit = () => {
    if (!dirty) {
      onCancel();
      return;
    }
    if (!valid) return;
    dispatch({
      type: "APPEND_OP",
      op: { op: "set-program-name", name: trimmed },
    });
    onCommit();
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="text-xs text-muted-foreground">
        Renames this program everywhere it appears — the handoff card in
        the rendered video, the breadcrumb above, the run picker, and
        the program list. The URL slug stays the same.
      </div>

      <section className="flex flex-col gap-1.5">
        <label htmlFor="program-name-input" className="text-xs font-medium uppercase tracking-wide">
          Program name
        </label>
        <input
          id="program-name-input"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          className="w-full rounded border bg-background p-2 text-sm"
          placeholder="Child Health Campaign"
        />
        {!valid && (
          <p className="text-[11px] text-amber-700 dark:text-amber-500">
            Program name can't be empty.
          </p>
        )}
      </section>

      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border px-3 py-1.5 text-sm"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={commit}
          disabled={!dirty || !valid}
          className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
        >
          Done
        </button>
      </div>
    </div>
  );
}
