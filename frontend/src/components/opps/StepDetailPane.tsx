import { useEffect, useState } from "react";

import { getStepDetail } from "../../api/opps";
import type { StepDetail } from "../../api/types";
import { ArtifactPreview } from "./ArtifactPreview";
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

  useEffect(() => {
    setLoading(true);
    getStepDetail(slug, runId, skill)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [slug, runId, skill]);

  if (loading) return <LoadingSpinner label={`Loading ${skill}…`} />;
  if (!detail)
    return (
      <div className="p-4 text-xs text-zinc-500">
        Failed to load {skill}.
      </div>
    );

  const primaryArtifact = detail.artifacts[0] ?? null;

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-4">
      <div>
        <div className="text-[9px] uppercase tracking-wider text-zinc-500">
          Selected step
        </div>
        <div className="text-sm font-semibold text-zinc-100">{detail.skill_name}</div>
        <div className="text-[10px] text-zinc-500">
          {detail.phase_display} · status <span className="text-zinc-300">{detail.status}</span>
        </div>
      </div>

      <DiscussInChatButton slug={slug} runId={runId} skill={skill} />
      <ArtifactPreview primaryArtifact={primaryArtifact} primaryBody={detail.primary_body} />
      <JudgeVerdict judge={detail.judge} />
      {detail.gates.length > 0 && <GateHistory gates={detail.gates} />}
      <LinkedChats slug={slug} runId={runId} skill={skill} />
    </div>
  );
}
