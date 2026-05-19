import { useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";

interface Props {
  clipKind: "scene-clip" | "product-beat";
  index: number;
  onCommit: () => void;
  onCancel: () => void;
}

function aliasFromRef(r: string): string | null {
  return r.startsWith("@") ? r.slice(1) : null;
}

/**
 * Swap the source clip in a beat slot. Lists every alias in
 * spec.manifest as a clickable tile with a video thumbnail (served by
 * the same serve_media endpoint the rendered explorer uses, so the
 * preview frames come from the *same* mp4 the renderer will splice).
 *
 * Why aliases (not arbitrary library entries)? The renderer's
 * applyManifestRefs() requires every `@alias` to resolve through the
 * spec's manifest. Picking outside the manifest would mean adding a
 * new entry, which is a bigger change than swap-among-existing.
 * Adding "browse the wider library + add to manifest" is a natural
 * follow-up — for now this panel covers the common case.
 */
export function ClipPickerPanel({ clipKind, index, onCommit, onCancel }: Props) {
  const { effectiveSpec, workspaceSlug, programSlug, runId, dispatch } = useBeatEditor();

  const slot = clipKind === "scene-clip"
    ? effectiveSpec.scene?.clips[index]
    : effectiveSpec.product?.beats[index];
  const currentRef = typeof slot === "string" ? slot : slot?.asset ?? "";
  const currentAlias = aliasFromRef(currentRef);

  const manifest = effectiveSpec.manifest ?? {};
  // Sort: current first, then alphabetical. The current slot's alias
  // gets a "current" badge so the user knows which one they're
  // looking at before picking a replacement.
  const aliases = Object.keys(manifest).sort((a, b) => {
    if (a === currentAlias) return -1;
    if (b === currentAlias) return 1;
    return a.localeCompare(b);
  });

  const prefix = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const mediaUrlFor = (alias: string) =>
    `${prefix}/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/${alias}.mp4`;

  const [hovered, setHovered] = useState<string | null>(null);

  const swap = (newAlias: string) => {
    if (newAlias === currentAlias) {
      onCancel();
      return;
    }
    dispatch({
      type: "APPEND_OP",
      op: { op: "set-clip-asset", kind: clipKind, index, alias: newAlias },
    });
    onCommit();
  };

  if (aliases.length === 0) {
    return (
      <div className="rounded border border-dashed bg-muted/20 p-4 text-sm text-muted-foreground">
        No clips defined in <code>spec.manifest</code>. Add entries to the manifest
        (mapping aliases to <code>gdrive:</code> ids) before swapping.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        Pick a different clip from this program's manifest. The choice replaces the
        slot's source — your existing trim values are preserved.
      </div>
      <div className="grid grid-cols-2 gap-3">
        {aliases.map((alias) => {
          const isCurrent = alias === currentAlias;
          return (
            <button
              type="button"
              key={alias}
              onClick={() => swap(alias)}
              onMouseEnter={() => setHovered(alias)}
              onMouseLeave={() => setHovered((h) => (h === alias ? null : h))}
              className={`flex flex-col gap-2 rounded border p-2 text-left transition-colors ${
                isCurrent
                  ? "border-primary bg-primary/5"
                  : "border-muted hover:border-primary"
              }`}
            >
              <div className="relative">
                <video
                  src={mediaUrlFor(alias)}
                  preload="metadata"
                  muted
                  // Briefly playing on hover would help users tell what's
                  // in the clip, but auto-play on hover trips Chrome's
                  // autoplay heuristics for muted previews — skip for
                  // now. The metadata-only preload still shows the first
                  // frame.
                  className="h-24 w-full rounded bg-black object-cover"
                />
                {isCurrent && (
                  <span className="absolute right-1 top-1 rounded-full bg-primary px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary-foreground">
                    Current
                  </span>
                )}
              </div>
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">@{alias}</code>
              {hovered === alias && !isCurrent && (
                <span className="text-[10px] text-muted-foreground">Click to swap</span>
              )}
            </button>
          );
        })}
      </div>
      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border px-3 py-1.5 text-sm"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
