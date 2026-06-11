import { useEffect, useState } from "react";
import { AlertTriangle, Plus, X } from "lucide-react";
import {
  createVideoProgram,
  listVideoTemplates,
  getVideoTemplate,
  type TemplateMeta,
} from "@/api/videos";

interface Props {
  workspaceSlug: string;
  onCreated: (slug: string) => void;
  onClose: () => void;
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

export function NewProgramDialog({ workspaceSlug, onCreated, onClose }: Props) {
  const [templates, setTemplates] = useState<TemplateMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listVideoTemplates(workspaceSlug)
      .then((t) => {
        if (cancelled) return;
        setTemplates(t);
        if (t.length === 1) setSelectedId(t[0].id);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [workspaceSlug]);

  const onNameChange = (v: string) => {
    setName(v);
    if (!slugEdited) setSlug(slugify(v));
  };

  const valid = selectedId && name.trim().length > 0 && slug.length > 0;

  const handleCreate = async () => {
    if (!valid || creating) return;
    setCreating(true);
    setError(null);
    try {
      const bundle = await getVideoTemplate(workspaceSlug, selectedId);
      const now = new Date().toISOString();
      const specYaml = bundle.skeleton_yaml
        .replace(/\{\{program_slug\}\}/g, slug)
        .replace(/\{\{workspace_slug\}\}/g, workspaceSlug)
        .replace(/\{\{program_name\}\}/g, name.trim())
        .replace(/\{\{template_id\}\}/g, selectedId)
        .replace(/\{\{generated_at\}\}/g, now)
        .replace(/\{\{program_url\}\}/g, "")
        .replace(/\{\{country_focus\}\}/g, "")
        .replace(/\{\{status\}\}/g, "Draft")
        .replace(/\{\{program_tagline\}\}/g, "")
        .replace(/\{\{scene_lower_third\}\}/g, "")
        .replace(/\{\{problem_big\}\}/g, "")
        .replace(/\{\{problem_caption\}\}/g, "")
        .replace(/\{\{problem_source\}\}/g, "")
        .replace(/\{\{impact_\d+_big\}\}/g, "")
        .replace(/\{\{impact_\d+_caption\}\}/g, "")
        .replace(/\{\{narration_\w+\}\}/g, "");
      const result = await createVideoProgram(workspaceSlug, slug, specYaml);
      onCreated(result.program_slug);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="relative w-full max-w-lg rounded-lg border bg-background p-6 shadow-xl">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-3 top-3 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>

        <h2 className="mb-4 text-lg font-semibold">New video program</h2>

        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
            <div className="text-muted-foreground">{error}</div>
          </div>
        )}

        <div className="flex flex-col gap-4">
          <section>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Template
            </label>
            {templates === null ? (
              <div className="text-sm text-muted-foreground">Loading templates…</div>
            ) : templates.length === 0 ? (
              <div className="rounded border border-dashed p-3 text-sm text-muted-foreground">
                No templates found. Add a template directory under{" "}
                <code className="rounded bg-muted px-1 text-xs">templates/</code> in the
                video-production tree.
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {templates.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setSelectedId(t.id)}
                    className={`rounded border p-3 text-left transition-colors ${
                      selectedId === t.id
                        ? "border-primary bg-primary/5"
                        : "border-muted hover:border-primary"
                    }`}
                  >
                    <div className="text-sm font-medium">{t.name}</div>
                    <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                      {t.description}
                    </div>
                    <div className="mt-1 text-[10px] text-muted-foreground">
                      {t.intended_audience.split("\n")[0]}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section>
            <label htmlFor="np-name" className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Program name
            </label>
            <input
              id="np-name"
              type="text"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder="e.g. Child Health Campaign"
              className="w-full rounded border bg-background px-3 py-2 text-sm"
              autoFocus
            />
          </section>

          <section>
            <label htmlFor="np-slug" className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Slug
            </label>
            <input
              id="np-slug"
              type="text"
              value={slug}
              onChange={(e) => { setSlug(e.target.value); setSlugEdited(true); }}
              placeholder="child-health-campaign"
              className="w-full rounded border bg-background px-3 py-2 font-mono text-sm"
            />
            <p className="mt-1 text-[11px] text-muted-foreground">
              Drive folder name + URL path. Lowercase, hyphens only.
            </p>
          </section>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border px-4 py-2 text-sm"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!valid || creating}
            onClick={handleCreate}
            className="inline-flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            {creating ? "Creating…" : "Create program"}
          </button>
        </div>
      </div>
    </div>
  );
}
