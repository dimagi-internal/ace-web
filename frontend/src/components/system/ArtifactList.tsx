import type { ArtifactRef } from "./types";

interface Props {
  produced: ArtifactRef[];
  consumed: ArtifactRef[];
}

export function ArtifactList({ produced, consumed }: Props) {
  if (produced.length === 0 && consumed.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      {produced.map((a) => (
        <ArtifactItem key={a.path} artifact={a} role="produces" />
      ))}
      {consumed.map((a) => (
        <ArtifactItem key={a.path} artifact={a} role="consumes" />
      ))}
    </div>
  );
}

function ArtifactItem({ artifact, role }: { artifact: ArtifactRef; role: "produces" | "consumes" }) {
  return (
    <div className="flex items-center gap-2 rounded border border-border bg-card px-2.5 py-1.5 text-xs">
      <span className="font-mono text-foreground">{artifact.path}</span>
      <span className="ml-auto flex-shrink-0 text-[10px] font-semibold uppercase" style={{
        color: role === "produces" ? "var(--status-ok)" : "var(--status-info)",
      }}>
        {role}
      </span>
    </div>
  );
}
