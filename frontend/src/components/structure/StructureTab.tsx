import { useEffect, useState } from "react";

import { getSessionStructure } from "../../api/structure";
import type { StructureTree } from "../../api/types.ws";
import { ApiError } from "../../api/client";
import { formatDuration, formatTokens, formatUsd, totalTokens } from "../../lib/format";
import { StatusIcon } from "./StatusIcon";
import { StructurePhaseRow } from "./StructurePhaseRow";
import { StructureViewContext } from "./structureContext";

interface Props {
  slug: string;
  workspaceSlug: string;
}

const UNAVAILABLE_MESSAGES = {
  "no-raw-jsonl":
    "This session has no persisted raw transcript. Re-upload via /ace:upload-transcript to enable the structure view.",
  "parse-failed":
    "Could not parse the persisted transcript for this session. Try re-uploading via /ace:upload-transcript.",
} as const;

export function StructureTab({ slug, workspaceSlug }: Props) {
  const [tree, setTree] = useState<StructureTree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showTools, setShowTools] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setTree(null);
    setError(null);
    getSessionStructure(slug, workspaceSlug)
      .then((data) => {
        if (!cancelled) setTree(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          if (err instanceof ApiError) setError(err.message);
          else setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [slug, workspaceSlug]);

  if (error) return <div className="text-sm text-destructive p-4">Failed to load: {error}</div>;
  if (tree === null) return <div className="text-sm text-muted-foreground p-4">Loading…</div>;

  if (tree.schema_version === 0 || tree.session === null) {
    const reason = tree.unavailable_reason ?? "no-raw-jsonl";
    const message = UNAVAILABLE_MESSAGES[reason] ?? UNAVAILABLE_MESSAGES["no-raw-jsonl"];
    return (
      <div className="text-sm text-muted-foreground p-4 space-y-2">
        <p>{message}</p>
      </div>
    );
  }

  const t = tree.session;
  return (
    <StructureViewContext.Provider value={{ showTools }}>
      <div className="space-y-2 p-4">
        <div className="flex items-center gap-4 text-sm pb-2">
          <StatusIcon status={t.status} />
          <div>
            <div className="text-muted-foreground text-xs uppercase">Wall time</div>
            <div className="text-lg font-medium">{formatDuration(t.wall_time_seconds)}</div>
          </div>
          <div>
            <div className="text-muted-foreground text-xs uppercase">Cost</div>
            <div className="text-lg font-medium">
              {formatUsd(t.estimated_cost_usd, t.cost_is_partial)}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground text-xs uppercase">Tokens</div>
            <div className="text-lg font-medium tabular-nums">
              {formatTokens(totalTokens(t.tokens))}
            </div>
          </div>
          <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showTools}
              onChange={(e) => setShowTools(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            Show tool calls
          </label>
        </div>
        <div>
          {tree.phases.map((p) => (
            <StructurePhaseRow key={p.name} phase={p} />
          ))}
        </div>
      </div>
    </StructureViewContext.Provider>
  );
}
