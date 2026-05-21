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

  // Compute the slot's duration in the FINAL video. The beat's total
  // seconds is divided evenly across all clip slots — so a clip's
  // trim window only affects which sub-region of the source plays;
  // the on-screen duration is fixed at slotSeconds.
  const beatId = clipKind === "scene-clip" ? "scene" : "product";
  const beat = (effectiveSpec.beats ?? []).find((b) => b.id === beatId);
  const totalSlots = clipKind === "scene-clip"
    ? (effectiveSpec.scene?.clips?.length ?? 1)
    : (effectiveSpec.product?.beats?.length ?? 1);
  const slotSeconds = beat && totalSlots > 0 ? beat.seconds / totalSlots : 0;

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
  const [mediaLoadFailed, setMediaLoadFailed] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  // End-time guard for the "Play selected clip" button. While set, a
  // timeupdate listener pauses playback once currentTime crosses this
  // mark. Cleared on manual pause/seek so the user regains normal
  // scrubbing without an invisible auto-pause lurking.
  const playUntilRef = useRef<number | null>(null);

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
    playUntilRef.current = null;
    const safe = Math.max(0, Math.min((v.duration || sourceDuration) - 0.05, draft.start));
    try { v.currentTime = safe; } catch { /* swallow */ }
  }, [draft?.start, sourceDuration]);

  // Auto-pause the player when "Play selected clip" reaches the end of
  // the slot window. timeupdate fires ~4×/sec which is plenty for the
  // 2–4s slots we typically render; overshoot is bounded by one frame.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => {
      const stopAt = playUntilRef.current;
      if (stopAt != null && v.currentTime >= stopAt) {
        v.pause();
        playUntilRef.current = null;
      }
    };
    // Clear the guard on user-driven pause so a later native Play
    // doesn't surprise-pause at the previous slot end. Our own auto-
    // pause already nulled the ref, so the duplicate clear is a no-op.
    const clearGuard = () => { playUntilRef.current = null; };
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("pause", clearGuard);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("pause", clearGuard);
    };
  }, []);

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

  const ready = sourceDuration > 0;

  // Slot length actually played in the final video — slotSeconds for
  // beat clips (the fixed window), draft.duration for the rare
  // variable-length caller.
  const playWindow = slotSeconds > 0 ? slotSeconds : (draft.duration || sourceDuration);

  const playSelectedClip = () => {
    const v = videoRef.current;
    if (!v || !ready) return;
    const start = Math.max(0, Math.min(sourceDuration - 0.05, draft.start));
    const end = Math.min(sourceDuration, start + playWindow);
    try { v.currentTime = start; } catch { /* swallow */ }
    playUntilRef.current = end;
    void v.play().catch(() => { playUntilRef.current = null; });
  };

  // Clamp helper used by both numeric inputs so a user typing 999 into
  // duration doesn't silently bypass [0, sourceDuration]. The TrimBar
  // already clamps via its onChange path; this mirrors the same bounds
  // for the keyboard entry path.
  const MIN_DURATION = 0.3;
  function clampStart(v: number): number {
    if (!ready) return v;
    return Math.max(0, Math.min(sourceDuration - MIN_DURATION, v));
  }
  function clampDuration(v: number, start: number): number {
    if (!ready) return v;
    return Math.max(MIN_DURATION, Math.min(sourceDuration - start, v));
  }

  // Format a seconds value as M:SS.s for human-readable display.
  const fmtMS = (n: number) => {
    const m = Math.floor(n / 60);
    const s = n - m * 60;
    return `${m}:${s.toFixed(1).padStart(4, "0")}`;
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Bold up-front summary. The two numbers that matter most are
          (a) how long this clip plays in the final video, and (b) where
          in the source clip the playback reads from. Putting them at
          the top — above the source preview — removes the "what am I
          even editing?" cold-open feel of the older layout where the
          play time only appeared in a paragraph at the bottom. */}
      {slotSeconds > 0 && (
        <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs">
          <div className="font-medium text-foreground">
            Plays <span className="text-base">{slotSeconds.toFixed(1)}s</span> in the final video
          </div>
          <div className="mt-0.5 text-muted-foreground">
            Reading from <span className="font-mono">{fmtMS(draft.start)} → {fmtMS(draft.start + slotSeconds)}</span>
            {sourceDuration > 0 && (
              <> of the <span className="font-mono">{fmtMS(sourceDuration)}</span> source clip</>
            )}
            {totalSlots > 1 && (
              <> · clip {index + 1} of {totalSlots} in this beat ({(slotSeconds * totalSlots).toFixed(1)}s total)</>
            )}
          </div>
        </div>
      )}
      {src && !mediaLoadFailed && (
        <video
          ref={videoRef}
          src={src}
          controls
          preload="metadata"
          onError={() => setMediaLoadFailed(true)}
          // Cap the preview height so the trim controls stay in view.
          // The 480px-wide drawer at aspect-video was ~270px tall — too
          // dominant when the rest of the panel is what the user is
          // actually adjusting.
          className="max-h-48 w-full rounded bg-black object-contain"
        />
      )}
      {src && mediaLoadFailed && (
        <div className="rounded border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
          Source clip <code className="rounded bg-muted px-1">@{alias}</code> isn't cached on this
          host yet — run <code className="rounded bg-muted px-1">npm run hydrate -- --program={programSlug}</code> to
          pull it from Drive, or click <strong>Re-render</strong> (the renderer hydrates as part
          of its setup). Trim values can still be edited blind via the inputs below.
        </div>
      )}
      {ready ? (
        <TrimBar
          sourceDuration={sourceDuration}
          start={draft.start}
          // When slotSeconds is set (always, for beat clip slots), the
          // TrimBar enters fixed-window mode: a draggable slotSeconds-
          // wide window the user slides along the source. Two-handle
          // resize is hidden because the renderer always plays exactly
          // slotSeconds from start_seconds regardless of duration.
          duration={draft.duration || slotSeconds || sourceDuration}
          playWindow={slotSeconds > 0 ? slotSeconds : undefined}
          onChange={(next) => setDraft({ ...draft, start: next.start_seconds, duration: next.duration_seconds })}
        />
      ) : (
        // Skeleton — empty handles at 0% with "0.00s / 0.00s" inputs
        // looked broken. Show a clear loading state until the video
        // probe finishes.
        <div className="flex h-9 items-center justify-center rounded bg-muted text-xs text-muted-foreground">
          Loading clip…
        </div>
      )}
      <div className="flex items-center gap-3 font-mono text-xs text-muted-foreground">
        <label className="flex items-center gap-1" title="Where in the source clip playback starts.">
          source start
          <input
            type="number" step="0.1" min={0} max={sourceDuration}
            disabled={!ready}
            value={draft.start.toFixed(2)}
            onChange={(e) => {
              const raw = parseFloat(e.target.value) || 0;
              const start = clampStart(raw);
              setDraft({ ...draft, start, duration: clampDuration(draft.duration || sourceDuration, start) });
            }}
            className="w-20 rounded border bg-background px-1 py-0.5 disabled:opacity-50"
          />
          s
        </label>
        {slotSeconds <= 0 && (
          // Variable-length selection: kept for any future caller that
          // genuinely needs to pick a duration. For normal beat slots
          // (slotSeconds > 0) the playback duration is fixed by the
          // beat split, so showing an editable "selection" input would
          // misleadingly imply the user can change playback length.
          <label
            className="flex items-center gap-1"
            title="How much of the source the slot consumes."
          >
            selection
            <input
              type="number" step="0.1" min={0.3} max={sourceDuration}
              disabled={!ready}
              value={(draft.duration || sourceDuration).toFixed(2)}
              onChange={(e) => {
                const raw = parseFloat(e.target.value) || 0;
                setDraft({ ...draft, duration: clampDuration(raw, draft.start) });
              }}
              className="w-20 rounded border bg-background px-1 py-0.5 disabled:opacity-50"
            />
            s
          </label>
        )}
        {ready && (
          <span className="ml-auto text-xs">
            source: {sourceDuration.toFixed(1)}s
          </span>
        )}
      </div>
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={playSelectedClip} disabled={!ready || mediaLoadFailed}
                title={`Play just this ${playWindow.toFixed(1)}s slice`}
                className="mr-auto rounded border px-3 py-1.5 text-sm disabled:opacity-50">
          Play selected clip
        </button>
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
