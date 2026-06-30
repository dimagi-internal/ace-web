import { useEffect, useState } from "react";
import { toast } from "sonner";

import { artifactBodyUrl, writeArtifact } from "@/api/opps";
import { Button } from "canopy-ui/ui";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "canopy-ui/ui";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  workspaceSlug: string;
  slug: string;
  runId: string;
  skill: string;
  artifactName: string;
}

export function EditArtifactDialog({ open, onOpenChange, workspaceSlug, slug, runId, skill, artifactName }: Props) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    let cancelled = false;
    fetch(artifactBodyUrl(workspaceSlug, slug, runId, skill, artifactName), { credentials: "include" })
      .then((r) => r.text())
      .then((text) => {
        if (!cancelled) setContent(text);
      })
      .catch((e) => {
        if (!cancelled) toast.error(`Failed to load: ${(e as Error).message}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, slug, runId, skill, artifactName]);

  async function save() {
    setSaving(true);
    try {
      await writeArtifact(workspaceSlug, slug, runId, skill, artifactName, content);
      toast.success(`${artifactName} saved`);
      onOpenChange(false);
    } catch (e) {
      toast.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>Edit {artifactName}</DialogTitle>
          <DialogDescription className="font-mono text-xs">
            {slug} / {runId} / {skill}
          </DialogDescription>
        </DialogHeader>
        {loading ? (
          <div className="p-3 text-xs text-muted-foreground">Loading…</div>
        ) : (
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={24}
            className="w-full rounded border border-border bg-card p-3 font-mono text-xs"
          />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
          <Button onClick={save} disabled={loading || saving}>
            {saving ? "Saving…" : "Save to Drive"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
