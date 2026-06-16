import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";

interface Props {
  onCommit: () => void;
  onCancel: () => void;
}

export function AiBuildPanel({ onCommit, onCancel }: Props) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const card = effectiveSpec.ai_build ?? { headline: "", components: [], subhead: "" };
  const [headline, setHeadline] = useState(card.headline);
  const [components, setComponents] = useState<string[]>(card.components);
  const [subhead, setSubhead] = useState(card.subhead ?? "");

  const cleaned = components.map((c) => c.trim()).filter(Boolean);
  const dirty =
    headline !== card.headline ||
    JSON.stringify(cleaned) !== JSON.stringify(card.components) ||
    subhead !== (card.subhead ?? "");

  const setChip = (i: number, v: string) =>
    setComponents((prev) => prev.map((c, idx) => (idx === i ? v : c)));
  const removeChip = (i: number) => setComponents((prev) => prev.filter((_, idx) => idx !== i));
  const addChip = () => setComponents((prev) => [...prev, ""]);

  const commit = () => {
    if (!dirty) return;
    dispatch({
      type: "APPEND_OP",
      op: { op: "set-ai-build", headline, components: cleaned, subhead },
    });
    onCommit();
  };

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Headline</span>
        <input
          aria-label="headline"
          value={headline}
          onChange={(e) => setHeadline(e.target.value)}
          className="w-full rounded border bg-background p-2 text-lg font-semibold"
        />
      </label>

      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Chips ({cleaned.length})
        </span>
        <div className="flex flex-col gap-1.5">
          {components.map((c, i) => (
            <div key={i} className="flex gap-2">
              <input
                aria-label={`chip ${i + 1}`}
                value={c}
                onChange={(e) => setChip(i, e.target.value)}
                className="flex-1 rounded border bg-background p-1.5 text-sm"
              />
              <button
                type="button"
                onClick={() => removeChip(i)}
                className="rounded border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                aria-label={`remove chip ${i + 1}`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={addChip}
          className="mt-1 self-start rounded border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
        >
          + Add chip
        </button>
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Subhead (optional)</span>
        <textarea
          aria-label="subhead"
          value={subhead}
          onChange={(e) => setSubhead(e.target.value)}
          rows={2}
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
