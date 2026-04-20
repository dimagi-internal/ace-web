import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { updateOppTags } from "../../api/opps";

interface Props {
  slug: string;
  initialTags: string[];
  onChanged?: (tags: string[]) => void;
}

export function TagEditor({ slug, initialTags, onChanged }: Props) {
  const [tags, setTags] = useState<string[]>(initialTags);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTags(initialTags);
  }, [initialTags]);

  const persist = async (next: string[]) => {
    setSaving(true);
    setError(null);
    try {
      const resp = await updateOppTags(slug, next);
      setTags(resp.tags);
      onChanged?.(resp.tags);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const addTag = async () => {
    const clean = input.trim();
    if (!clean || tags.includes(clean)) {
      setInput("");
      return;
    }
    setInput("");
    await persist([...tags, clean]);
  };

  const removeTag = async (t: string) => {
    await persist(tags.filter((x) => x !== t));
  };

  return (
    <div className="flex items-center gap-1 text-xs">
      <span className="text-muted-foreground">tags:</span>
      {tags.map((t) => (
        <span
          key={t}
          className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-primary"
        >
          {t}
          <button
            type="button"
            onClick={() => removeTag(t)}
            disabled={saving}
            className="text-primary/70 hover:text-primary disabled:opacity-50"
            aria-label={`Remove tag ${t}`}
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void addTag();
          }
        }}
        onBlur={() => {
          if (input.trim()) void addTag();
        }}
        placeholder="+ add tag"
        disabled={saving}
        className="w-24 rounded border border-input bg-card px-2 py-0.5 text-xs placeholder:text-muted-foreground focus:border-ring focus:outline-none disabled:opacity-50"
      />
      {error && <span className="text-destructive">{error}</span>}
    </div>
  );
}
