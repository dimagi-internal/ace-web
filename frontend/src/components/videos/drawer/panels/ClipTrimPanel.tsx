import { useEffect, useRef, useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";
import { TrimBar } from "../TrimBar";

interface Props {
  clipKind: "scene-clip" | "product-beat";
  index: number;
  onCommit: () => void;
  onCancel: () => void;
}

function aliasFromRef(r: string): string | null {
  return r.startsWith("@") ? r.slice(1) : null;
}

export function ClipTrimPanel({ clipKind, index, onCommit, onCancel }: Props) {
  const { effectiveSpec, workspaceSlug, programSlug, runId, dispatch } = useBeatEditor();
  const slot = clipKind === "scene-clip"
    ? effectiveSpec.scene?.clips[index]
    : effectiveSpec.product?.beats[index];

  const initial = (() => {
    if (slot === undefined) return null;
    const obj = typeof slot === "string" ? { asset: slot } : slot;
    return {
      asset: obj.asset,
      start: obj.start_seconds ?? 0,
      duration: obj.duration_seconds ?? 0,
    };
  })();

  const [draft, setDraft] = useState(initial);
  const [sourceDuration, setSourceDuration] = useState<number>(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Probe the source video for its real duration on load.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onMeta = () => {
      setSourceDuration(v.duration);
      // Do NOT rewrite the draft here — keep draft.duration === 0 for
      // untrimmed clips so `dirty` stays false until the user actually
      // drags the TrimBar (or edits a numeric input). The TrimBar /
      // inputs render `draft.duration || sourceDuration` so the UI still
      // shows the full clip duration while initial state is preserved.
    };
    v.addEventListener("loadedmetadata", onMeta);
    return () => v.removeEventListener("loadedmetadata", onMeta);
  }, []);

  // Live-seek the preview to the trim IN-point.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !draft || v.readyState < 1) return;
    if (!v.paused) v.pause();
    const safe = Math.max(0, Math.min((v.duration || sourceDuration) - 0.05, draft.start));
    try { v.currentTime = safe; } catch { /* swallow */ }
  }, [draft?.start, sourceDuration]);

  if (!initial || !draft) return <div>(clip not found)</div>;

  const alias = aliasFromRef(initial.asset);
  const src = alias
    ? `/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/${alias}.mp4`
    : null;

  const commit = () => {
    dispatch({
      type: "APPEND_OP",
      op: {
        op: "set-clip-trim", kind: clipKind, index,
        start_seconds: parseFloat(draft.start.toFixed(2)),
        duration_seconds: parseFloat(draft.duration.toFixed(2)),
      },
    });
    onCommit();
  };

  const dirty = draft.start !== initial.start || draft.duration !== initial.duration;

  return (
    <div className="flex flex-col gap-3">
      {src && (
        <video
          ref={videoRef}
          src={src}
          controls
          preload="metadata"
          className="aspect-video w-full rounded bg-black"
        />
      )}
      <TrimBar
        sourceDuration={sourceDuration || 1}
        start={draft.start}
        duration={draft.duration || sourceDuration}
        onChange={(next) => setDraft({ ...draft, start: next.start_seconds, duration: next.duration_seconds })}
      />
      <div className="flex items-center gap-3 font-mono text-xs text-muted-foreground">
        <label className="flex items-center gap-1">
          start
          <input
            type="number" step="0.1" min={0} max={sourceDuration}
            value={draft.start.toFixed(2)}
            onChange={(e) => setDraft({ ...draft, start: parseFloat(e.target.value) || 0 })}
            className="w-20 rounded border bg-background px-1 py-0.5"
          />
          s
        </label>
        <label className="flex items-center gap-1">
          duration
          <input
            type="number" step="0.1" min={0.3} max={sourceDuration}
            value={(draft.duration || sourceDuration).toFixed(2)}
            onChange={(e) => setDraft({ ...draft, duration: parseFloat(e.target.value) || 0 })}
            className="w-20 rounded border bg-background px-1 py-0.5"
          />
          s
        </label>
      </div>
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={onCancel}
                className="rounded border px-3 py-1.5 text-sm">
          Cancel
        </button>
        <button type="button" onClick={commit} disabled={!dirty}
                className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          Done
        </button>
      </div>
    </div>
  );
}
