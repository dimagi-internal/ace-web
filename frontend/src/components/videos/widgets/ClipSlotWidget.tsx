import { useBeatEditor } from "../BeatEditorContext";
import type { ClipObject } from "../types";

interface Props {
  beatId: string;
  clipKind: "scene-clip" | "product-beat";
  index: number;
}

function aliasFromRef(ref: string): string | null {
  if (typeof ref === "string" && ref.startsWith("@")) return ref.slice(1);
  return null;
}

export function ClipSlotWidget({ beatId, clipKind, index }: Props) {
  const { effectiveSpec, workspaceSlug, programSlug, runId, dispatch } = useBeatEditor();
  const slot =
    clipKind === "scene-clip"
      ? effectiveSpec.scene?.clips[index]
      : effectiveSpec.product?.beats[index];

  if (slot === undefined) return null;
  const ref = typeof slot === "string" ? slot : slot.asset;
  const obj: ClipObject = typeof slot === "string" ? { asset: slot } : slot;
  const alias = aliasFromRef(ref) ?? "(literal path)";
  const trim =
    obj.start_seconds !== undefined && obj.duration_seconds !== undefined
      ? `${obj.start_seconds.toFixed(1)}s → ${(obj.start_seconds + obj.duration_seconds).toFixed(1)}s · ${obj.duration_seconds.toFixed(1)}s`
      : "untrimmed";

  // Source-clip MP4 served by the existing serve_media endpoint.
  const mediaUrl =
    alias && alias !== "(literal path)"
      ? `/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/${alias}.mp4`
      : null;

  return (
    <div
      className="cursor-pointer rounded border bg-muted/40 p-3 hover:border-primary"
      onClick={() =>
        dispatch({
          type: "OPEN_DRAWER",
          target: { kind: "clip-trim", clipKind, beatId, index },
        })
      }
    >
      <header className="mb-2 flex items-center gap-2">
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">@{alias}</code>
        <span className="ml-auto text-xs text-muted-foreground">click to edit</span>
      </header>
      {mediaUrl && (
        <video
          src={mediaUrl}
          preload="metadata"
          muted
          className="mb-2 aspect-video w-full rounded bg-black"
        />
      )}
      <div className="font-mono text-xs text-muted-foreground">{trim}</div>
    </div>
  );
}
