import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, LayoutTemplate } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { WorkbenchLayout, usePaneCollapsed } from "@/components/workbench";
import { listVideoTemplates, type TemplateMeta } from "@/api/videos";

export default function TemplatesPage() {
  const { workspaceSlug } = useParams<{ workspaceSlug: string }>();
  const [templates, setTemplates] = useState<TemplateMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  // Left rail collapse state (persisted per browser).
  const { collapsed: railCollapsed, toggle: toggleRailCollapsed } =
    usePaneCollapsed("ace.templates.railCollapsed");

  useEffect(() => {
    if (!workspaceSlug) return;
    let cancelled = false;
    listVideoTemplates(workspaceSlug)
      .then((data) => {
        if (!cancelled) {
          setTemplates(data);
          if (data.length > 0 && selected === null) setSelected(data[0].id);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug]); // eslint-disable-line react-hooks/exhaustive-deps

  const railContent = (
    <nav aria-label="Templates">
      {templates === null && !error ? (
        <div className="space-y-1 p-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : templates && templates.length === 0 ? (
        <p className="p-3 text-xs text-muted-foreground">No templates found.</p>
      ) : (
        <ul className="py-1">
          {templates?.map((t) => (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => setSelected(t.id)}
                className={`w-full px-3 py-2 text-left text-sm transition hover:bg-muted/60 ${
                  selected === t.id ? "bg-muted font-medium" : ""
                }`}
              >
                {t.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );

  const activeTemplate = templates?.find((t) => t.id === selected) ?? null;

  const centerContent = (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-6 flex items-center gap-2">
        <LayoutTemplate className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-2xl font-semibold">Templates</h1>
        <Link
          to={`/w/${workspaceSlug}/videos`}
          className="ml-auto text-sm text-muted-foreground underline hover:text-foreground"
        >
          ← Back to programs
        </Link>
      </header>

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
          <div>
            <div className="font-medium">Couldn't load templates</div>
            <div className="text-muted-foreground">{error}</div>
          </div>
        </div>
      )}

      {templates === null && !error ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : templates && templates.length === 0 ? (
        <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
          No templates defined for this workspace yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {templates?.map((t) => (
            <article
              key={t.id}
              className={`rounded border bg-card p-4 transition hover:border-primary ${
                selected === t.id ? "border-primary" : "border-border"
              }`}
            >
              <header className="mb-2 flex items-start justify-between gap-2">
                <h2 className="text-base font-medium">{t.name}</h2>
                <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                  ~{t.expected_duration_seconds}s
                </span>
              </header>

              {t.description && (
                <p className="mb-3 text-sm text-muted-foreground">{t.description}</p>
              )}

              {t.intended_audience && (
                <p className="mb-1 text-xs text-muted-foreground">
                  <span className="font-medium">Audience:</span> {t.intended_audience}
                </p>
              )}

              <div className="mt-3 flex items-center justify-end">
                <Link
                  to={`/w/${workspaceSlug}/videos/templates/${t.id}`}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium transition hover:border-primary hover:text-primary"
                >
                  Edit
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Detail panel for selected template (when rail is collapsed) */}
      {activeTemplate && railCollapsed && (
        <div className="mt-8 rounded-md border p-4">
          <h3 className="mb-1 text-sm font-medium">{activeTemplate.name}</h3>
          <p className="text-xs text-muted-foreground">{activeTemplate.when_to_use}</p>
        </div>
      )}
    </div>
  );

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col">
      <WorkbenchLayout
        left={{
          title: "Templates",
          collapsed: railCollapsed,
          onToggle: toggleRailCollapsed,
          expandedWidth: 240,
          minWidth: 180,
          maxWidth: 400,
          resizable: true,
          content: railContent,
        }}
        center={centerContent}
      />
    </div>
  );
}
