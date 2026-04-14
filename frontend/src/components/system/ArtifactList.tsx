import type { ArtifactRef } from "./types";

interface Props {
  produced: ArtifactRef[];
  consumed: ArtifactRef[];
}

export function ArtifactList({ produced, consumed }: Props) {
  if (produced.length === 0 && consumed.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {produced.length > 0 && (
        <ArtifactGroup
          title={`Produces (${produced.length})`}
          color="var(--status-ok)"
          artifacts={produced}
        />
      )}
      {consumed.length > 0 && (
        <ArtifactGroup
          title={`Consumes (${consumed.length})`}
          color="var(--status-info)"
          artifacts={consumed}
        />
      )}
    </div>
  );
}

function ArtifactGroup({
  title,
  color,
  artifacts,
}: {
  title: string;
  color: string;
  artifacts: ArtifactRef[];
}) {
  return (
    <div>
      <div
        className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider"
        style={{ color }}
      >
        {title}
      </div>
      <div className="flex flex-col gap-1">
        {artifacts.map((a) => (
          <div
            key={a.path}
            className="rounded border border-border bg-card px-2.5 py-1.5"
          >
            <div className="font-mono text-xs text-foreground">{a.path}</div>
            {a.description && (
              <div className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                {a.description}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
