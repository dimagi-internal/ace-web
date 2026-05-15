import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";
import type { PendingChange, ProgramSpec, Stat } from "../../types";

interface Props {
  path: string;
  onCommit: () => void;
  onCancel: () => void;
}

function resolveStat(spec: ProgramSpec, path: string): Stat | null {
  if (path === "problem") return spec.problem ?? null;
  const m = /^impact\[(\d+)\]$/.exec(path);
  if (!m) return null;
  return spec.impact?.[parseInt(m[1], 10)] ?? null;
}

export function StatPanel({ path, onCommit, onCancel }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const initial = resolveStat(effectiveSpec, path);
  const [big, setBig] = useState(initial?.big ?? "");
  const [caption, setCaption] = useState(initial?.caption ?? "");
  const [source, setSource] = useState(initial?.source ?? "");

  if (!initial) return <div>(stat not found)</div>;

  const dirty =
    big !== initial.big ||
    caption !== initial.caption ||
    source !== (initial.source ?? "");

  const commit = () => {
    if (!dirty) return;
    const op: Extract<PendingChange, { op: "set-stat" }> = { op: "set-stat", path };
    if (big !== initial.big) op.big = big;
    if (caption !== initial.caption) op.caption = caption;
    if (source !== (initial.source ?? "")) op.source = source; // "" clears
    dispatch({ type: "APPEND_OP", op });
    onCommit();
  };

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Big</span>
        <input
          aria-label="big"
          value={big}
          onChange={(e) => setBig(e.target.value)}
          className="w-full rounded border bg-background p-2 text-2xl font-bold"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Caption</span>
        <textarea
          aria-label="caption"
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          rows={2}
          className="w-full rounded border bg-background p-2 text-sm"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Source (optional)</span>
        <div className="flex gap-2">
          <input
            aria-label="source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="flex-1 rounded border bg-background p-2 text-sm"
          />
          <button type="button" onClick={() => setSource("")}
                  className="rounded border px-2 py-1 text-xs">
            Clear source
          </button>
        </div>
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
