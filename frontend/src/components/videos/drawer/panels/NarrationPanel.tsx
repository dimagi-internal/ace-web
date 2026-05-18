import { useEffect, useRef, useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";

interface Props {
  beatId: string;
  onCommit: () => void;
  onCancel: () => void;
}

// Mirrors `cacheKey(script, voiceId, model)` in
// video-production/connect-videos/src/lib/voiceover.ts (sha256 of
// `${voiceId}::${model}::${script}`, truncated to 16 hex chars). Used
// to compute the audio-library stream URL for the current narration
// so the user can preview the cached voiceover before editing.
async function audioCacheKey(text: string, voiceId: string, model: string): Promise<string> {
  const data = new TextEncoder().encode(`${voiceId}::${model}::${text}`);
  const hash = await crypto.subtle.digest("SHA-256", data);
  const hex = Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return hex.slice(0, 16);
}

export function NarrationPanel({ beatId, onCommit, onCancel }: Props) {
  const { effectiveSpec, workspaceSlug, dispatch } = useBeatEditor();
  const initial = effectiveSpec.narration?.by_beat?.[beatId] ?? "";
  const [text, setText] = useState(initial);
  const dirty = text !== initial;

  const voice = effectiveSpec.voice?.voice_id ?? "(default)";
  const model = effectiveSpec.voice?.model ?? "(default)";

  // Resolve the cached audio URL for the *initial* narration so the
  // user can hear what's currently in the rendered video before
  // typing replacement text. As soon as text is dirty, we mark the
  // clip as "stale" (still playable, but the labels reflect that
  // a re-render is needed).
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioMissing, setAudioMissing] = useState<boolean>(false);
  useEffect(() => {
    let cancelled = false;
    if (!initial || !voice || voice === "(default)") {
      setAudioUrl(null);
      return;
    }
    audioCacheKey(initial, voice, model).then((hash) => {
      if (cancelled) return;
      const prefix = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
      setAudioUrl(`${prefix}/api/w/${workspaceSlug}/videos/library/audio/${hash}/stream`);
    });
    return () => {
      cancelled = true;
    };
  }, [initial, voice, model, workspaceSlug]);
  const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
  const estSec = Math.round((text.length / 15) * 10) / 10;

  // The beat's allotted seconds in the final video. Used to warn when
  // estimated read time overflows the slot (synth may get cut off).
  const beat = (effectiveSpec.beats ?? []).find((b) => b.id === beatId);
  const beatSeconds = beat?.seconds ?? 0;
  const overflow = beatSeconds > 0 && estSec > beatSeconds + 0.3;

  // Auto-grow textarea — content-driven height, clamped to [min, max]
  // line-height windows so short text doesn't waste space and long text
  // stays readable without an internal scroll.
  const taRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const max = 480;  // ~24 lines
    const min = 96;   // ~5 lines
    ta.style.height = Math.max(min, Math.min(max, ta.scrollHeight)) + "px";
  }, [text]);

  const commit = () => {
    if (!dirty) return;
    dispatch({ type: "APPEND_OP", op: { op: "set-narration", beatId, text } });
    onCommit();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      commit();
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        Voice <code className="rounded bg-muted px-1">{voice}</code> ·
        model <code className="rounded bg-muted px-1">{model}</code>
      </div>
      {audioUrl && !audioMissing && (
        <div>
          <div className="mb-1 text-xs text-muted-foreground">
            {dirty ? "Currently rendered (will resynth on Re-render):" : "Currently rendered:"}
          </div>
          <audio
            controls
            preload="metadata"
            className="h-9 w-full"
            src={audioUrl}
            onError={() => setAudioMissing(true)}
          />
        </div>
      )}
      <textarea
        ref={taRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        className="w-full resize-none rounded border bg-background p-2 font-sans text-sm leading-relaxed"
      />
      <div className={overflow ? "text-xs font-medium text-amber-700" : "text-xs text-muted-foreground"}>
        {wordCount} word{wordCount === 1 ? "" : "s"} · ~{estSec}s read
        {beatSeconds > 0 && (
          <span className="ml-2">
            of <strong>{beatSeconds.toFixed(1)}s</strong> slot
          </span>
        )}
        {overflow && (
          <span className="ml-2">
            ⚠ overflows — synth may get cut off
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Identical text reuses the cached audio — no resynth on Re-render.
      </p>
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
