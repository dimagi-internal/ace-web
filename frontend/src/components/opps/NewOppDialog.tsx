import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { createOpp } from "@/api/opps";
import { Button } from "@canopy/workbench/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@canopy/workbench/ui";
import { cn } from "@/lib/utils";

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$/;

function deriveSlug(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  workspaceSlug: string;
}

export function NewOppDialog({ open, onOpenChange, workspaceSlug }: Props) {
  const navigate = useNavigate();
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [idea, setIdea] = useState("");
  const [mode, setMode] = useState<"auto" | "review">("review");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const slugValid = SLUG_RE.test(slug);
  const canSubmit = slugValid && displayName.trim() && idea.trim() && !submitting;

  function handleDisplayNameChange(v: string) {
    setDisplayName(v);
    if (!slugTouched) setSlug(deriveSlug(v));
  }

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      const result = await createOpp(workspaceSlug, { slug, display_name: displayName, idea, mode });
      navigate(`/w/${workspaceSlug}/opps/${encodeURIComponent(result.slug)}`);
    } catch (e) {
      setError(String((e as Error).message ?? e));
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create a new opp</DialogTitle>
          <DialogDescription>
            Creates <code className="font-mono">ACE/&lt;slug&gt;/</code> in Drive
            and starts a working chat session.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <label className="flex flex-col gap-1 text-sm">
            Display name
            <Input
              value={displayName}
              onChange={(e) => handleDisplayNameChange(e.target.value)}
              placeholder="Malaria Pilot 2026"
              autoFocus
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Slug (kebab-case, must be unique)
            <Input
              value={slug}
              onChange={(e) => {
                setSlugTouched(true);
                setSlug(e.target.value.toLowerCase());
              }}
              placeholder="malaria-pilot-2026"
              className={cn(slug && !slugValid && "border-destructive")}
            />
            {slug && !slugValid && (
              <span className="text-xs text-destructive">
                Lowercase letters, digits, hyphens. Can't start or end with a hyphen.
              </span>
            )}
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Initial idea
            <textarea
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              rows={6}
              className="rounded border border-border bg-card p-2 font-mono text-xs"
              placeholder="Describe the intervention: what, who, how..."
            />
          </label>

          <label className="flex items-center gap-3 text-sm">
            Mode:
            <label className="flex items-center gap-1">
              <input
                type="radio"
                checked={mode === "review"}
                onChange={() => setMode("review")}
              />
              review (recommended)
            </label>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                checked={mode === "auto"}
                onChange={() => setMode("auto")}
              />
              auto
            </label>
          </label>

          {error && (
            <div className="rounded border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
              {error}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? "Creating…" : "Create opp"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
