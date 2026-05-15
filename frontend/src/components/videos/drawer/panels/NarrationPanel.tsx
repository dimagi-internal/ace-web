import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";

interface Props {
  beatId: string;
  onCommit: () => void;
  onCancel: () => void;
}

export function NarrationPanel({ beatId, onCommit, onCancel }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const initial = effectiveSpec.narration?.by_beat?.[beatId] ?? "";
  const [text, setText] = useState(initial);
  const dirty = text !== initial;

  const voice = effectiveSpec.voice?.voice_id ?? "(default)";
  const model = effectiveSpec.voice?.model ?? "(default)";
  const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
  const estSec = Math.round((text.length / 15) * 10) / 10;

  const commit = () => {
    if (!dirty) return;
    dispatch({ type: "APPEND_OP", op: { op: "set-narration", beatId, text } });
    onCommit();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      commit();
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        Voice <code className="rounded bg-muted px-1">{voice}</code> ·
        model <code className="rounded bg-muted px-1">{model}</code>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        rows={8}
        className="w-full rounded border bg-background p-2 font-sans text-sm"
      />
      <div className="text-xs text-muted-foreground">
        {wordCount} word{wordCount === 1 ? "" : "s"} · ~{estSec}s read
      </div>
      <p className="text-xs text-muted-foreground">
        Identical text reuses the cached audio — no resynth on Re-render.
      </p>
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={onCancel}
                className="rounded border px-3 py-1.5 text-sm">
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
