import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Plus, Video } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { NewProgramDialog } from "@/components/videos/NewProgramDialog";
import { listVideoPrograms, type VideoProgramCard } from "@/api/videos";

export default function VideosListPage() {
  const navigate = useNavigate();
  const { workspaceSlug } = useParams<{ workspaceSlug: string }>();
  const [programs, setPrograms] = useState<VideoProgramCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNewDialog, setShowNewDialog] = useState(false);

  useEffect(() => {
    if (!workspaceSlug) return;
    let cancelled = false;
    listVideoPrograms(workspaceSlug)
      .then((data) => {
        if (!cancelled) setPrograms(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug]);

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-6 flex items-center gap-2">
        <Video className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-2xl font-semibold">Videos</h1>
        <div className="ml-auto flex items-center gap-3">
          <Link
            to={`/w/${workspaceSlug}/videos/templates`}
            className="text-sm text-muted-foreground underline hover:text-foreground"
          >
            Templates →
          </Link>
          <Link
            to={`/w/${workspaceSlug}/videos/library`}
            className="text-sm text-muted-foreground underline hover:text-foreground"
          >
            Media library →
          </Link>
          <button
            type="button"
            onClick={() => setShowNewDialog(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            New program
          </button>
        </div>
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Video programs for this workspace. Each program has one or more runs
        — edit clips, narration, and stats in the beat editor, then re-render
        to produce the draft MP4.
      </p>

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
          <div>
            <div className="font-medium">Couldn't load programs</div>
            <div className="text-muted-foreground">{error}</div>
          </div>
        </div>
      )}

      {programs === null && !error ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : programs && programs.length === 0 ? (
        <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
          <p className="mb-3">No video programs yet in this workspace.</p>
          <button
            type="button"
            onClick={() => setShowNewDialog(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            Create your first program
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {programs?.map((p) => (
            <Link
              key={p.slug}
              to={`/w/${workspaceSlug}/videos/${p.slug}`}
              className="group block overflow-hidden rounded border border-border bg-card transition hover:border-primary"
            >
              <div className="p-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h2 className="text-base font-medium">{p.name}</h2>
                  {!p.has_explorer_build && (
                    <Badge variant="outline" className="text-xs">
                      not built
                    </Badge>
                  )}
                </div>
                {p.tagline && (
                  <p className="mb-3 line-clamp-2 text-sm text-muted-foreground">
                    {p.tagline}
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {p.country_focus && <span>{p.country_focus}</span>}
                  {p.country_focus && <span aria-hidden>·</span>}
                  <span>
                    {p.manifest_count} clip{p.manifest_count === 1 ? "" : "s"}
                  </span>
                  {p.status && (
                    <>
                      <span aria-hidden>·</span>
                      <span>{p.status}</span>
                    </>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {showNewDialog && workspaceSlug && (
        <NewProgramDialog
          workspaceSlug={workspaceSlug}
          onCreated={(slug) => {
            setShowNewDialog(false);
            navigate(`/w/${workspaceSlug}/videos/${slug}`);
          }}
          onClose={() => setShowNewDialog(false)}
        />
      )}
    </div>
  );
}
