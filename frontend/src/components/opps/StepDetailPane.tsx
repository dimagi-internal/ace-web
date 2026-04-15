import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";

import { getStepDetail } from "../../api/opps";
import type { Artifact, StepDetail } from "../../api/types";
import { cn } from "@/lib/utils";
import { ArtifactBody } from "./ArtifactBody";
import { DiscussInChatButton } from "./DiscussInChatButton";
import { GateHistory } from "./GateHistory";
import { JudgeVerdict } from "./JudgeVerdict";
import { LinkedChats } from "./LinkedChats";
import { LoadingSpinner } from "./LoadingStates";

interface Props {
  slug: string;
  runId: string;
  skill: string;
}

export function StepDetailPane({ slug, runId, skill }: Props) {
  const [detail, setDetail] = useState<StepDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null);

  useEffect(() => {
    setLoading(true);
    getStepDetail(slug, runId, skill)
      .then((d) => {
        setDetail(d);
        setActiveArtifact(d.artifacts[0] ?? null);
      })
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [slug, runId, skill]);

  if (loading) return <LoadingSpinner label={`Loading ${skill}…`} />;
  if (!detail)
    return (
      <div className="p-4 text-xs text-muted-foreground">
        Failed to load {skill}.
      </div>
    );

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <div>
        <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
          Selected step
        </div>
        <div className="text-sm font-semibold text-foreground">{detail.skill_name}</div>
        <div className="text-[10px] text-muted-foreground">
          {detail.phase_display} · status <span className="text-foreground">{detail.status}</span>
        </div>
      </div>

      <DiscussInChatButton slug={slug} runId={runId} skill={skill} />

      {detail.artifacts.length > 0 && (
        <div>
          <div className="mb-1.5 text-[9px] uppercase tracking-wider text-muted-foreground">
            Artifacts
          </div>
          <div className="flex flex-col gap-1">
            {detail.artifacts.map((a) => (
              <div
                key={a.name}
                className={cn(
                  "flex items-center gap-2 rounded border px-2 py-1 text-[11px]",
                  activeArtifact?.name === a.name
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
                {a.drive_web_link && (
                  <a
                    href={a.drive_web_link}
                    target="_blank"
                    rel="noreferrer"
                    className="text-muted-foreground hover:text-foreground"
                    title="Open in Drive"
                  >
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {activeArtifact && (
        <div className="rounded border border-border">
          <div className="border-b border-border bg-card px-3 py-1.5 font-mono text-[10px] text-muted-foreground">
            {activeArtifact.name}
          </div>
          <ArtifactBody
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
      {detail.gates.length > 0 && <GateHistory gates={detail.gates} />}
      <LinkedChats slug={slug} runId={runId} skill={skill} />
    </div>
  );
}
