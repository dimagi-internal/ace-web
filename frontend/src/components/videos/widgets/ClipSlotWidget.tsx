import { useState } from "react";
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
  const [mediaLoadFailed, setMediaLoadFailed] = useState(false);
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
  // The backend resolves broken symlinks (host-side hydrate cache that
  // the container can't see) by re-fetching the gdrive id via the
  // workspace SA, so previews now work even when the explorer media
  // dir is full of symlinks pointing into a non-mounted host home.
  // The `/api/...` URL is prefixed with BASE_URL so ace-web's `/ace/*`
  // ALB tenant path is honoured in production (Vite's bare-prefix
  // proxy was masking this locally).
  const prefix = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const mediaUrl =
    alias && alias !== "(literal path)"
      ? `${prefix}/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/${alias}.mp4`
      : null;
  const showVideo = mediaUrl && !mediaLoadFailed;

  return (
    <div
      data-testid="clip-slot-widget"
      data-clip-kind={clipKind}
      data-index={index}
      className="group cursor-pointer rounded border bg-muted/40 p-3 hover:border-primary"
      onClick={() =>
        dispatch({
          type: "OPEN_DRAWER",
          target: { kind: "clip-trim", clipKind, beatId, index },
        })
      }
    >
      <header className="mb-2 flex items-center gap-2">
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">@{alias}</code>
        <span aria-hidden className="ml-auto text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
          ✏ Edit trim
        </span>
      </header>
      <div className="flex items-start gap-3">
        {/* Thumbnail-sized preview (not full-width 16:9). The in-page
            card is for orientation; the drawer panel is where the user
            actually inspects/scrubs the clip at higher fidelity. */}
        {showVideo ? (
          <video
            src={mediaUrl!}
            preload="metadata"
            muted
            onError={() => setMediaLoadFailed(true)}
            className="h-20 w-36 flex-shrink-0 rounded bg-black object-cover"
          />
        ) : (
          <div className="flex h-20 w-36 flex-shrink-0 items-center justify-center rounded border border-dashed bg-muted/40 text-center text-[10px] text-muted-foreground">
            {mediaUrl ? "preview not cached on host" : "literal path"}
          </div>
        )}
        <div className="flex-1 font-mono text-xs text-muted-foreground">{trim}</div>
      </div>
    </div>
  );
}
