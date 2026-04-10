import { useState, type KeyboardEvent } from "react";

interface Props {
  value: string;
  onSave: (newTitle: string) => Promise<void>;
}

export function InlineTitleEdit({ value, onSave }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  const start = () => {
    setDraft(value);
    setEditing(true);
  };

  const commit = async () => {
    if (draft !== value) {
      await onSave(draft);
    }
    setEditing(false);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      void commit();
    }
    if (e.key === "Escape") {
      setDraft(value);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        className="rounded border border-ring bg-background px-2 py-1 text-lg font-semibold text-foreground outline-none"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
      />
    );
  }
  return (
    <button
      type="button"
      onClick={start}
      className="rounded px-1 text-lg font-semibold text-foreground hover:bg-accent"
    >
      {value || "Untitled"}
    </button>
  );
}
