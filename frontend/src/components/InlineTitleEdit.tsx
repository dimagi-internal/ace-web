import { Pencil } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

interface Props {
  value: string;
  onSave: (newTitle: string) => Promise<void>;
  size?: "lg" | "sm";
}

export function InlineTitleEdit({ value, onSave, size = "lg" }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  const start = () => {
    setDraft(value);
    setEditing(true);
  };

  const commit = async () => {
    const next = draft.trim();
    if (next && next !== value) {
      await onSave(next);
    }
    setEditing(false);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void commit();
    }
    if (e.key === "Escape") {
      setDraft(value);
      setEditing(false);
    }
  };

  const textClass =
    size === "lg"
      ? "text-lg font-semibold"
      : "text-sm font-medium";

  if (editing) {
    return (
      <input
        autoFocus
        className={`rounded border border-ring bg-background px-2 py-1 text-foreground outline-none ${textClass}`}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
        onClick={(e) => e.stopPropagation()}
      />
    );
  }
  return (
    <button
      type="button"
      onClick={start}
      title="Click to rename"
      className={`group inline-flex items-center gap-1.5 rounded px-1 text-foreground hover:bg-accent ${textClass}`}
    >
      <span className="truncate">{value || "Untitled"}</span>
      <Pencil
        className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
        aria-hidden
      />
    </button>
  );
}
