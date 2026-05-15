import { useEffect, useState } from "react";
import { ExternalLink, Pencil } from "lucide-react";

import { getStepDetail } from "../../api/opps";
import type { Artifact, StepDetail } from "../../api/types.ws";
import { cn } from "@/lib/utils";
import { ArtifactBody } from "./ArtifactBody";
import { DiscussInChatButton } from "./DiscussInChatButton";
import { EditArtifactDialog } from "./EditArtifactDialog";
import { JudgeVerdict } from "./JudgeVerdict";
import { PatientLoader } from "./LoadingStates";

interface Props {
  workspaceSlug: string;
  slug: string;
  runId: string;
  skill: string;
  // Human label for the selected skill (e.g. "Idea to PDD"). When the
  // detail payload arrives it carries its own display_name; this prop
  // is just so the loading state shows the friendly name instead of
  // the raw slug.
  skillDisplayName?: string;
}

export function StepDetailPane({ workspaceSlug, slug, runId, skill, skillDisplayName }: Props) {
  const [detail, setDetail] = useState<StepDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null);
  const [editing, setEditing] = useState<Artifact | null>(null);

  useEffect(() => {
    setLoading(true);
    getStepDetail(workspaceSlug, slug, runId, skill)
      .then((d) => {
        setDetail(d);
        setActiveArtifact(d.artifacts[0] ?? null);
      })
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [slug, runId, skill]);

  if (loading)
    return (
      <PatientLoader
        label={`Loading ${skillDisplayName || skill}…`}
        slowLabel="Drive is slow today — still fetching this step's artifacts."
      />
    );
  if (!detail)
    return (
      <div className="p-4 text-xs text-destructive">
        Couldn't load {skillDisplayName || skill} — Drive may be slow or rate-limited.
      </div>
    );

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <div>
        <div
          className="text-sm font-semibold text-foreground"
          title={detail.skill_name}
        >
          {detail.display_name || detail.skill_name}
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
          <span>{detail.phase_display}</span>
          <span aria-hidden>·</span>
          <StatusPill status={detail.status} />
        </div>
      </div>

      {detail.artifacts.length > 0 && (
        <div>
          <div className="mb-1.5 text-[9px] uppercase tracking-wider text-muted-foreground">
            Artifacts
          </div>
          <div className="flex flex-col gap-1">
            {detail.artifacts.map((a) => {
              const isActive = activeArtifact?.name === a.name;
              return (
                <div
                  key={a.name}
                  className={cn(
                    "flex items-center gap-2 rounded border px-2 py-1 text-[11px]",
                    isActive
                      ? "border-primary bg-primary/5"
                      : "border-border bg-card hover:bg-accent",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => setActiveArtifact(a)}
                    className="flex-1 truncate text-left font-mono"
                  >
                    {a.name}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditing(a);
                    }}
                    className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                    aria-label={`Edit ${a.name}`}
                    title="Edit"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  {/* Hide the row-level Drive link for the ACTIVE artifact —
                      the viewer header below already shows "Open in Drive",
                      and two identical links 30px apart is just clutter. */}
                  {a.drive_web_link && !isActive && (
                    <a
                      href={a.drive_web_link}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                      aria-label={`Open ${a.name} in Drive`}
                      title="Open in Drive"
                    >
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {activeArtifact && (
        <div className="rounded border border-border">
          <div className="flex items-center justify-between gap-2 border-b border-border bg-card px-3 py-1.5 font-mono text-[10px] text-muted-foreground">
            <span className="truncate">{activeArtifact.name}</span>
            {activeArtifact.drive_web_link && (
              <a
                href={activeArtifact.drive_web_link}
                target="_blank"
                rel="noreferrer"
                className="flex shrink-0 items-center gap-1 font-sans hover:text-foreground"
                title="Open in Drive"
              >
                Open in Drive
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
          <ArtifactBody
            workspaceSlug={workspaceSlug}
            slug={slug}
            runId={runId}
            skill={skill}
            artifactName={activeArtifact.name}
            mimeType={activeArtifact.mime_type ?? ""}
            webViewLink={activeArtifact.drive_web_link}
          />
        </div>
      )}

      <JudgeVerdict judge={detail.judge} />

      <DiscussInChatButton workspaceSlug={workspaceSlug} slug={slug} runId={runId} skill={skill} />

      {editing && (
        <EditArtifactDialog
          open={editing !== null}
          onOpenChange={(v) => !v && setEditing(null)}
          workspaceSlug={workspaceSlug}
          slug={slug}
          runId={runId}
          skill={skill}
          artifactName={editing.name}
        />
      )}
    </div>
  );
}

// Same status palette as SkillRow's StatusDot, just rendered as a
// labeled pill so the status is legible in the step-detail header
// without having to look back to the lifecycle column.
function StatusPill({ status }: { status: string }) {
  const tone =
    status === "complete" ? "border-green-500/40 bg-green-500/10 text-green-500"
    : status === "running" ? "border-blue-500/40 bg-blue-500/10 text-blue-400"
    : status === "judge-fail" || status === "error" ? "border-destructive/40 bg-destructive/10 text-destructive"
    : "border-border bg-muted text-muted-foreground";
  const label =
    status === "complete" ? "complete"
    : status === "running" ? "running"
    : status === "judge-fail" ? "judge failed"
    : status === "error" ? "error"
    : status === "skipped" ? "skipped"
    : status === "pending" ? "not started"
    : status;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${tone}`}
    >
      {label}
    </span>
  );
}
