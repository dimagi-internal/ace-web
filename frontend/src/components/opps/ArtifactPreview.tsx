import type { Artifact } from "../../api/types";

interface Props {
  primaryArtifact: Artifact | null;
  primaryBody: string;
}

export function ArtifactPreview({ primaryArtifact, primaryBody }: Props) {
  if (!primaryArtifact) {
    return (
      <div className="rounded bg-card p-2.5">
        <div className="text-[9px] uppercase tracking-wider text-muted-foreground">Artifact</div>
        <div className="text-[10px] text-muted-foreground">— no artifacts</div>
      </div>
    );
  }
  const lines = primaryBody.split("\n").slice(0, 10).join("\n");
  return (
    <div className="rounded bg-card p-2.5">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
        Artifact · {primaryArtifact.name}
      </div>
      <pre className="mt-1.5 max-h-40 overflow-hidden rounded bg-background p-2 text-[9px] text-muted-foreground">
        {lines || "(empty)"}
      </pre>
      {primaryArtifact.drive_web_link && (
        <a
          href={primaryArtifact.drive_web_link}
          target="_blank"
          rel="noreferrer"
          className="mt-1.5 block text-[9px] text-primary underline"
        >
          open in Drive →
        </a>
      )}
    </div>
  );
}
