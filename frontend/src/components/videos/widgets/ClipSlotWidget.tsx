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

function formatMS(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

export function ClipSlotWidget({ beatId, clipKind, index }: Props) {
  const { effectiveSpec, workspaceSlug, programSlug, runId, dispatch } = useBeatEditor();
  const [mediaLoadFailed, setMediaLoadFailed] = useState(false);
  const [sourceDuration, setSourceDuration] = useState<number | null>(null);
  const slot =
    clipKind === "scene-clip"
      ? effectiveSpec.scene?.clips[index]
      : effectiveSpec.product?.beats[index];

  // Slot playback duration in the final = beat.seconds / N. The trim's
  // start_seconds is the in-point in the source; the renderer plays
  // exactly slotSeconds from there, regardless of duration_seconds.
  // (duration_seconds is bookkeeping for the trim's selection window.)
  const beatIdForLookup = clipKind === "scene-clip" ? "scene" : "product";
  const beat = (effectiveSpec.beats ?? []).find((b) => b.id === beatIdForLookup);
  const totalSlots = clipKind === "scene-clip"
    ? (effectiveSpec.scene?.clips?.length ?? 1)
    : (effectiveSpec.product?.beats?.length ?? 1);
  const slotSeconds = beat && totalSlots > 0 ? beat.seconds / totalSlots : 0;

  if (slot === undefined) return null;
  const ref = typeof slot === "string" ? slot : slot.asset;
  const obj: ClipObject = typeof slot === "string" ? { asset: slot } : slot;
  const alias = aliasFromRef(ref) ?? "(literal path)";

  // What the viewer sees: start → start + slotSeconds. We always render
  // this (not the selection range) so the card answers "what plays?"
  // not "what's selected?". When slotSeconds is unknown (no beat
  // metadata) we fall back to the legacy selection-range display.
  const inPoint = obj.start_seconds ?? 0;
  const playWindow = slotSeconds > 0
    ? `Plays ${formatMS(inPoint)} → ${formatMS(inPoint + slotSeconds)}${sourceDuration ? ` of ${formatMS(sourceDuration)} source` : ""}`
    : (obj.start_seconds !== undefined && obj.duration_seconds !== undefined
        ? `${obj.start_seconds.toFixed(1)}s → ${(obj.start_seconds + obj.duration_seconds).toFixed(1)}s · ${obj.duration_seconds.toFixed(1)}s`
        : "untrimmed");
  // A slot is "trimmed" if it doesn't play the entire source clip —
  // either the IN-point is past 0 (head discard) OR the play window
  // ends before the source ends (tail discard). The original predicate
  // only checked head discard, which made identical-shaped slots
  // inconsistent: e.g. start=0 plays=2.3s of 5.7s source looked
  // untrimmed while start=3.0 plays=2.3s of 23.4s source was tagged.
  // Tail discard needs sourceDuration, which is probed async from the
  // <video> element — until that resolves we conservatively answer
  // based on head discard alone.
  const TRIM_EPSILON = 0.05;
  const inPointTrimmed = inPoint > 0;
  const playEnd = inPoint + (slotSeconds > 0 ? slotSeconds : (obj.duration_seconds ?? 0));
  const tailTrimmed = sourceDuration != null && playEnd + TRIM_EPSILON < sourceDuration;
  const isExplicitlyTrimmed = inPointTrimmed || tailTrimmed;

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
        {isExplicitlyTrimmed && (
          <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-500">
            trimmed
          </span>
        )}
        {/* Right-side affordances. "Swap" opens the clip picker for
            this slot; the rest of the card (and the legacy "Edit trim"
            hint) keeps opening the trim drawer. Both buttons stop
            propagation so the card's catch-all onClick (which routes
            to trim) doesn't fire alongside. */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            dispatch({
              type: "OPEN_DRAWER",
              target: { kind: "clip-picker", clipKind, beatId, index },
            });
          }}
          className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          title="Pick a different clip from this program's manifest"
        >
          ↔ Swap
        </button>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors group-hover:text-foreground">
          ✏ Edit trim
        </span>
      </header>
      <div className="flex items-start gap-3">
        {/* Thumbnail-sized preview (not full-width 16:9). The in-page
            card is for orientation; the drawer panel is where the user
            actually inspects/scrubs the clip at higher fidelity. The
            `loadedmetadata` listener captures the source's true
            duration so we can show "of X.Xs source" without baking it
            into the spec. */}
        {showVideo ? (
          <video
            src={mediaUrl!}
            preload="metadata"
            muted
            onError={() => setMediaLoadFailed(true)}
            onLoadedMetadata={(e) => setSourceDuration(e.currentTarget.duration)}
            className="h-20 w-36 flex-shrink-0 rounded bg-black object-cover"
          />
        ) : (
          <div className="flex h-20 w-36 flex-shrink-0 items-center justify-center rounded border border-dashed bg-muted/40 text-center text-[10px] text-muted-foreground">
            {mediaUrl ? "preview not cached on host" : "literal path"}
          </div>
        )}
        <div className="flex-1 font-mono text-xs text-muted-foreground">{playWindow}</div>
      </div>
    </div>
  );
}
